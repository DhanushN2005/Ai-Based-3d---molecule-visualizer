import logging
import math
import os
import random
import re
import secrets
import sys
import threading
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from dotenv import load_dotenv
from flask import Flask, g, jsonify, render_template, request, send_from_directory, session

load_dotenv()  # read .env before anything reads os.environ

# Emoji in log messages crash on Windows' cp1252 when output is piped/redirected.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import requests
from rdkit import Chem, RDLogger
from rdkit.Chem import Descriptors, rdMolDescriptors
from rdkit.Geometry import Point3D

import accounts
from blender_script_gen import generate_blender_py
from elements import UNKNOWN_HEX, colors_for
from export_glb_blender import run_blender_script
from generate_xyz import build_molecule, write_xyz
from glb_trimesh import build_glb
from models import CustomMolecule, Explanation, QuizSession, database_url, db
from molecules_db import MOLECULE_DB
from ratelimit import _hits, rate_limit  # noqa: F401  (_hits is re-exported for the tests)
from ratelimit import allowed as _allowed

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("chemverse")

RDLogger.DisableLog("rdApp.*")  # PubChem SMILES can be noisy; errors are handled below

app = Flask(__name__)

DATA_DIR = os.environ.get("DATA_DIR", "data")


def _secret_key():
    key = os.environ.get("SECRET_KEY", "").strip()
    if key:
        return key
    log.warning("SECRET_KEY is not set: using a random key, so logins reset on every restart. "
                "Set SECRET_KEY in production.")
    return secrets.token_hex(32)


app.config.update(
    SECRET_KEY=_secret_key(),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE") == "1",   # set to 1 behind HTTPS
    PERMANENT_SESSION_LIFETIME=timedelta(days=14),
    SQLALCHEMY_DATABASE_URI=database_url(DATA_DIR),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
    MAX_CONTENT_LENGTH=64 * 1024,       # no endpoint needs a large body
)
db.init_app(app)
app.register_blueprint(accounts.bp)

# Behind a host's proxy (Render, Hugging Face...) every request would look like it comes
# from the proxy's IP, so the rate limiter would treat all users as one. Only enable this
# when the app really sits behind one, otherwise clients could spoof X-Forwarded-For.
if os.environ.get("TRUST_PROXY") == "1":
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

molecule_db = MOLECULE_DB
PT = Chem.GetPeriodicTable()
MAX_HEAVY_ATOMS = int(os.environ.get("MAX_HEAVY_ATOMS", "80"))


# ---------------------------------------------------------------- LLM (Groq)
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")
_explanations = {}  # cache: stable text per molecule, saves free-tier quota


class LLMUnavailable(Exception):
    pass


def _groq(messages, max_tokens=600):
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise LLMUnavailable("Set the GROQ_API_KEY environment variable.")
    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": 0.5,
        "max_tokens": max_tokens,
    }
    if "gpt-oss" in GROQ_MODEL:
        payload["reasoning_effort"] = "low"  # keep tokens for the answer, not thinking
    try:
        res = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {key}"},
            json=payload,
            timeout=30,
        )
        res.raise_for_status()
        return res.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.error("Groq request failed: %s", e)
        raise LLMUnavailable("The AI service is unavailable right now.") from e


def _stored_explanation(molecule):
    with app.app_context():
        row = db.session.get(Explanation, molecule)
        return row.text if row else None


def _store_explanation(molecule, text):
    with app.app_context():
        try:
            db.session.merge(Explanation(name=molecule, text=text))
            db.session.commit()
        except Exception:
            db.session.rollback()
            log.warning("Could not store the explanation for %s", molecule)


def explain_molecule(molecule: str) -> str:
    if molecule in _explanations:
        return _explanations[molecule]
    stored = _stored_explanation(molecule)
    if stored:
        _explanations[molecule] = stored
        return stored
    prompt = (
        f"Explain the molecule '{molecule}' to a school student in about 150 words. "
        "Cover its structure and formula, functional groups, physical and chemical "
        "properties, common uses, and any biological or environmental relevance. "
        "Plain text only, no markdown."
    )
    try:
        text = _groq([
            {"role": "system", "content": "You are a friendly chemistry teacher."},
            {"role": "user", "content": prompt},
        ])
    except LLMUnavailable as e:
        return f"Explanation unavailable: {e}"
    _explanations[molecule] = text
    _store_explanation(molecule, text)
    return text


# ------------------------------------------------- molecule lookup (+ PubChem)
PUBCHEM = "https://pubchem.ncbi.nlm.nih.gov/rest"
PUBCHEM_LOOKUPS_PER_MIN = int(os.environ.get("PUBCHEM_LOOKUPS_PER_MIN", "20"))
_custom = {}  # slug -> {"smiles": ..., "title": ...}, filled from PubChem
_custom_lock = threading.Lock()


class MoleculeError(Exception):
    """A problem the user can read and act on."""


def _load_custom():
    """Fill the in-process cache from the database (survives restarts)."""
    with app.app_context():
        for row in CustomMolecule.query.all():
            _custom[row.name] = {"smiles": row.smiles, "title": row.name}


def _persist_custom(key, smiles):
    with app.app_context():
        try:
            db.session.merge(CustomMolecule(name=key, smiles=smiles))
            db.session.commit()
        except Exception:
            db.session.rollback()
            log.warning("Could not store PubChem molecule %s", key)


def slugify(text):
    """Safe lowercase key used for molecule names AND file names (no path characters)."""
    s = re.sub(r"[^a-z0-9 \-]", "", str(text).lower())
    return re.sub(r"\s+", " ", s).strip()[:60]


def is_known(key):
    return key in molecule_db or key in _custom


with app.app_context():
    db.create_all()
_load_custom()
accounts.configure(slugify, is_known)


def smiles_of(key):
    return molecule_db[key] if key in molecule_db else _custom[key]["smiles"]


def pubchem_lookup(query):
    """Name -> SMILES from PubChem. Raises MoleculeError with a friendly message."""
    if not _allowed("pubchem", PUBCHEM_LOOKUPS_PER_MIN):
        raise MoleculeError("Too many new-molecule lookups. Please wait a minute.")
    log.info("PubChem lookup: %s", query)
    try:
        res = requests.get(
            f"{PUBCHEM}/pug/compound/name/{quote(query, safe='')}/property/SMILES,Title/JSON",
            timeout=15,
            headers={"User-Agent": "chemverse3d"},
        )
    except requests.RequestException as exc:
        raise MoleculeError("Could not reach PubChem. Check your internet connection.") from exc
    if res.status_code == 404:
        raise MoleculeError(f"'{query}' was not found in the built-in list or on PubChem.")
    if res.status_code in (429, 503):
        raise MoleculeError("PubChem is busy. Please try again in a few seconds.")
    if not res.ok:
        raise MoleculeError("PubChem returned an error. Please try again.")
    try:
        props = res.json()["PropertyTable"]["Properties"][0]
        smiles = props.get("SMILES") or props.get("IsomericSMILES") or props.get("CanonicalSMILES")
    except (KeyError, IndexError, ValueError):
        smiles = None
    if not smiles:
        raise MoleculeError(f"PubChem has no structure for '{query}'.")
    return smiles


def resolve_molecule(name):
    """Return a safe key for `name`, fetching from PubChem if needed."""
    key = slugify(name)
    if len(key) < 2:
        raise MoleculeError("Please enter a molecule name.")
    if is_known(key):
        return key
    smiles = pubchem_lookup(key)
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise MoleculeError(f"Could not read the structure for '{key}'.")
    if mol.GetNumHeavyAtoms() > MAX_HEAVY_ATOMS:
        raise MoleculeError(
            f"'{key}' is too large ({mol.GetNumHeavyAtoms()} heavy atoms; limit {MAX_HEAVY_ATOMS}).")
    try:
        get_mol(key, smiles)  # make sure a 3D structure can actually be built
    except Exception as exc:
        raise MoleculeError(f"Could not build a 3D structure for '{key}'.") from exc
    with _custom_lock:
        _custom[key] = {"smiles": smiles, "title": key}
    _persist_custom(key, smiles)
    return key


# ------------------------------------------------------- molecule data / GLB
_mols = {}
_infos = {}


def get_mol(name, smiles=None):
    if name not in _mols:
        _mols[name] = build_molecule(smiles or smiles_of(name), name)
    return _mols[name]


def molecule_info(name):
    """Everything the viewer needs, computed from the one RDKit conformer."""
    if name in _infos:
        return _infos[name]
    mol = get_mol(name)
    counts = {}
    for a in mol.GetAtoms():
        counts[a.GetAtomicNum()] = counts.get(a.GetAtomicNum(), 0) + 1
    elements = [
        {"symbol": PT.GetElementSymbol(z), "name": PT.GetElementName(z), "count": c}
        for z, c in sorted(counts.items(), key=lambda kv: (kv[0] != 6, kv[0] != 1, kv[0]))
    ]
    info = {
        "name": name,
        "title": name.title(),
        "smiles": smiles_of(name),
        "formula": rdMolDescriptors.CalcMolFormula(mol),
        "mass": round(Descriptors.MolWt(mol), 2),
        "atoms": mol.GetNumAtoms(),
        "heavy_atoms": mol.GetNumHeavyAtoms(),
        "bonds": mol.GetNumBonds(),
        "elements": elements,
        "colors": colors_for([e["symbol"] for e in elements]),
        "unknown_color": UNKNOWN_HEX,
        "molblock": Chem.MolToMolBlock(mol),
    }
    _infos[name] = info
    return info


def vibration_frames(name, n=24):
    """Multi-record SDF: the molecule jiggling about its equilibrium geometry.

    Lighter atoms move more, like real vibrations. One full cycle over n frames.
    """
    mol = get_mol(name)
    conf = mol.GetConformer()
    base = [conf.GetAtomPosition(i) for i in range(mol.GetNumAtoms())]
    rng = random.Random(1)
    motion = []
    for atom in mol.GetAtoms():
        v = [rng.gauss(0, 1) for _ in range(3)]
        norm = math.sqrt(sum(c * c for c in v)) or 1.0
        amp = 0.03 / math.sqrt(atom.GetMass() / 12.0)
        motion.append(([c / norm for c in v], amp, rng.uniform(0, 2 * math.pi)))

    records = []
    for f in range(n):
        phase = 2 * math.pi * f / n
        m = Chem.Mol(mol)
        c = m.GetConformer()
        for i, (d, amp, ph) in enumerate(motion):
            k = amp * math.sin(phase + ph)
            c.SetAtomPosition(i, Point3D(base[i].x + d[0] * k,
                                         base[i].y + d[1] * k,
                                         base[i].z + d[2] * k))
        records.append(Chem.MolToMolBlock(m) + "$$$$\n")
    return "".join(records)


def ensure_glb(name, mol, force=False):
    """Make outputs/<name>.glb: trimesh first, Blender as fallback."""
    path = f"outputs/{name}.glb"
    if os.path.exists(path) and not force:
        return path
    os.makedirs("outputs", exist_ok=True)
    if os.path.exists(path):
        os.remove(path)  # so an old file can't mask a failed export
    try:
        build_glb(mol, name)  # primary: pure Python, no Blender
    except Exception:
        log.exception("trimesh export failed for %s, falling back to Blender", name)
        try:
            run_blender_script(generate_blender_py(mol, name))
        except Exception:
            log.exception("Blender fallback failed too for %s", name)
    return path if os.path.exists(path) else None


# ------------------------------------------------------------------ quiz data
_quiz_cache = {}


def _plain(name):
    """Formula and per-element counts from SMILES only (no 3D build, so it is fast)."""
    if name not in _quiz_cache:
        m = Chem.AddHs(Chem.MolFromSmiles(smiles_of(name)))
        counts = {}
        for a in m.GetAtoms():
            counts[a.GetSymbol()] = counts.get(a.GetSymbol(), 0) + 1
        _quiz_cache[name] = {"formula": rdMolDescriptors.CalcMolFormula(m), "counts": counts}
    return _quiz_cache[name]


def make_quiz(n=10):
    seen, pool = set(), []
    for name, smi in molecule_db.items():  # drop synonyms such as aspirin / acetylsalicylic acid
        if smi not in seen:
            seen.add(smi)
            pool.append(name)
    picks = random.sample(pool, min(n, len(pool)))
    kinds = ["identify", "formula", "count"]
    questions = []
    for i, name in enumerate(picks):
        kind = kinds[i % 3] if i < 3 else random.choice(kinds)
        data = _plain(name)
        others = [x for x in pool if x != name]
        if kind == "identify":
            options = [name] + random.sample(others, 3)
            q = {"type": "identify", "text": "Which molecule is shown?",
                 "molblock": molecule_info(name)["molblock"],
                 "colors": molecule_info(name)["colors"]}
        elif kind == "formula":
            wrong = []
            for o in random.sample(others, len(others)):
                f = _plain(o)["formula"]
                if f != data["formula"] and f not in wrong:
                    wrong.append(f)
                if len(wrong) == 3:
                    break
            options = [data["formula"]] + wrong
            q = {"type": "formula", "text": f"What is the molecular formula of {name}?"}
        else:
            sym = random.choice([s for s in data["counts"] if s != "H"] or list(data["counts"]))
            real = data["counts"][sym]
            nums = {real}
            for d in (1, -1, 2, -2, 3):
                if real + d >= 0:
                    nums.add(real + d)
                if len(nums) == 4:
                    break
            options = [str(x) for x in sorted(nums)]
            correct = str(real)
            el_name = PT.GetElementName(PT.GetAtomicNumber(sym)).lower()
            info = molecule_info(name)
            q = {"type": "count", "text": f"How many {el_name} atoms does {name} contain?",
                 "molblock": info["molblock"], "colors": info["colors"]}
        if kind != "count":
            correct = options[0]
        random.shuffle(options)
        q["options"] = options
        q["answer"] = options.index(correct)
        q["explain"] = f"{name.title()} has the formula {data['formula']}."
        questions.append(q)
    return questions


# ----------------------------------------------------- headers / errors / health
CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "media-src 'self'",
    "connect-src 'self'",
    "worker-src 'self' blob:",
    "frame-ancestors 'self'",
    "base-uri 'self'",
    "form-action 'self'",
])


@app.after_request
def security_headers(resp):
    resp.headers.setdefault("Content-Security-Policy", CSP)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return resp


def _error(status, title, message):
    """JSON for API/POST callers, an HTML page for browsers."""
    if request.path.startswith("/api/") or request.method == "POST":
        return jsonify(success=False, error=message), status
    return render_template("error.html", title=title, message=message), status


@app.errorhandler(404)
def not_found(_e):
    return _error(404, "Page not found", "That page does not exist.")


@app.errorhandler(413)
def too_large(_e):
    return _error(413, "Request too large", "That request is too large.")


@app.errorhandler(405)
def bad_method(_e):
    return _error(405, "Method not allowed", "That request type is not allowed here.")


@app.errorhandler(500)
def server_error(_e):
    log.exception("Unhandled server error on %s", request.path)
    return _error(500, "Something went wrong", "Something went wrong on our side. Please try again.")


@app.route("/healthz")
def healthz():
    """Cheap liveness check for hosts and Docker (does no chemistry or network work)."""
    return jsonify(status="ok")


# -------------------------------------------------------------------- routes
@rate_limit(20)
def _build_from_form():
    try:
        name = resolve_molecule(request.form.get('molecule', ''))
        mol = get_mol(name)  # one conformer for everything
        write_xyz(mol, name)
        if ensure_glb(name, mol, force=True):
            log.info("GLB created: outputs/%s.glb", name)
        # The viewer draws from RDKit data, so it works even without a GLB.
        return jsonify(success=True, viewer_url=f"/viewer/{quote(name)}")
    except MoleculeError as e:
        return jsonify(success=False, error=str(e))
    except Exception:
        log.exception("Unexpected error building molecule")
        return jsonify(success=False, error="Something went wrong building that molecule.")


@app.route('/')
def cover():
    """Landing page: explains the app and links to the search. No login needed."""
    return render_template('cover.html', demo=molecule_info("caffeine"), count=len(molecule_db))


@app.route('/search', methods=['GET', 'POST'])
def search():
    if request.method == 'POST':
        return _build_from_form()
    return render_template('index.html', molecules=sorted(molecule_db))


@app.route('/viewer/<molecule>')
def viewer(molecule):
    try:
        name = resolve_molecule(molecule)  # also lets shared PubChem links work
    except MoleculeError as e:
        return render_template("error.html", title="Molecule not available", message=str(e)), 404
    info = molecule_info(name)
    has_glb = ensure_glb(name, get_mol(name)) is not None
    return render_template(
        "viewer.html",
        molecule=name,
        info=info,
        has_glb=has_glb,
        favorite=bool(g.user and accounts.is_favorite(g.user.id, name)),
        explanation=explain_molecule(name),
        molecules=sorted(molecule_db),
    )


@app.route('/compare')
def compare():
    infos, error = [], None
    for key in ("a", "b"):
        raw = request.args.get(key, "").strip()
        if not raw:
            infos.append(None)
            continue
        try:
            infos.append(molecule_info(resolve_molecule(raw)))
        except MoleculeError as e:
            infos.append(None)
            error = str(e)
    return render_template("compare.html", a=infos[0], b=infos[1], error=error,
                           molecules=sorted(molecule_db))


@app.route('/quiz')
def quiz():
    return render_template("quiz.html")


def _prune_quiz_sessions():
    """Drop unfinished quizzes older than a day so the table cannot grow without bound."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    try:
        QuizSession.query.filter(QuizSession.finished.is_(False), QuizSession.created_at < cutoff).delete()
        db.session.commit()
    except Exception:
        db.session.rollback()


@app.route('/api/quiz')
@rate_limit(30)
def api_quiz():
    """Start a quiz. Correct answers stay on the server; the browser only gets the questions."""
    try:
        n = max(3, min(int(request.args.get("n", 10)), 15))
    except ValueError:
        n = 10
    questions = make_quiz(n)
    _prune_quiz_sessions()
    quiz_id = str(uuid.uuid4())
    db.session.add(QuizSession(id=quiz_id, user_id=g.user.id if g.user else None,
                               questions=questions, responses={}, total=len(questions)))
    db.session.commit()
    public = [{k: v for k, v in q.items() if k not in ("answer", "explain")} for q in questions]
    return jsonify(quiz_id=quiz_id, questions=public, signed_in=g.user is not None)


def _quiz_or_404(quiz_id):
    return db.session.get(QuizSession, quiz_id)


@app.route('/api/quiz/<quiz_id>/answer', methods=['POST'])
@rate_limit(120)
def api_quiz_answer(quiz_id):
    session_row = _quiz_or_404(quiz_id)
    if session_row is None:
        return jsonify(error="Unknown quiz."), 404
    if session_row.finished:
        return jsonify(error="This quiz is already finished."), 409
    data = request.get_json(silent=True) or {}
    try:
        index, choice = int(data["question"]), int(data["choice"])
    except (KeyError, TypeError, ValueError):
        return jsonify(error="Send a question number and a choice."), 400
    if not (0 <= index < session_row.total and 0 <= choice < 4):
        return jsonify(error="Question or choice out of range."), 400
    if str(index) in session_row.responses:
        return jsonify(error="That question was already answered."), 409
    session_row.responses = {**session_row.responses, str(index): choice}   # reassign so the JSON change is saved
    db.session.commit()
    q = session_row.questions[index]
    return jsonify(correct=choice == q["answer"], answer=q["answer"], explain=q["explain"])


@app.route('/api/quiz/<quiz_id>/finish', methods=['POST'])
@rate_limit(30)
def api_quiz_finish(quiz_id):
    """The score is computed here from the stored answers; the browser cannot send its own."""
    session_row = _quiz_or_404(quiz_id)
    if session_row is None:
        return jsonify(error="Unknown quiz."), 404
    if not session_row.finished:
        session_row.score = sum(
            1 for i, q in enumerate(session_row.questions) if session_row.responses.get(str(i)) == q["answer"])
        session_row.finished = True
        # the 3D data is only needed while playing; keep the row small
        session_row.questions = [{k: v for k, v in q.items() if k not in ("molblock", "colors")}
                                 for q in session_row.questions]
        db.session.commit()
    if session_row.user_id is None and g.user is None:
        session[accounts.GUEST_QUIZ_KEY] = quiz_id      # lets a login right after this quiz claim it
    result = {"score": session_row.score, "total": session_row.total, "answered": len(session_row.responses)}
    if session_row.user_id:
        result["best"] = accounts.user_best(session_row.user_id)
        result["on_leaderboard"] = session_row.total == accounts.LEADERBOARD_QUIZ_SIZE
    return jsonify(result)


@app.route('/api/suggest')
@rate_limit(60)
def suggest():
    q = slugify(request.args.get("q", ""))
    if len(q) < 2:
        return jsonify(names=[])
    names = [n for n in sorted(molecule_db) if q in n][:5]
    try:
        res = requests.get(f"{PUBCHEM}/autocomplete/compound/{quote(q, safe='')}/json?limit=8",
                           timeout=6, headers={"User-Agent": "chemverse3d"})
        if res.ok:
            for n in res.json().get("dictionary_terms", {}).get("compound", []):
                n = slugify(n)
                if n and n not in names:
                    names.append(n)
    except (requests.RequestException, ValueError):
        pass  # suggestions are optional; built-in matches still work offline
    return jsonify(names=names[:10])


@app.route('/api/frames/<molecule>')
def frames(molecule):
    name = slugify(molecule)
    if not is_known(name):
        return jsonify(error="Unknown molecule."), 404
    return jsonify(sdf=vibration_frames(name))


@app.route('/api/ask', methods=['POST'])
@rate_limit(10)
def ask():
    data = request.get_json(silent=True) or {}
    name = slugify(data.get("molecule", ""))
    question = str(data.get("question", "")).strip()[:300]
    if not is_known(name):
        return jsonify(error="Unknown molecule."), 400
    if not question:
        return jsonify(error="Please type a question."), 400
    try:
        answer = _groq([
            {"role": "system", "content": (
                f"You are a friendly chemistry teacher. The student is looking at a 3D "
                f"model of {name}. Answer the student's question in at most 100 words, "
                f"plain text, no markdown. If it is unrelated to chemistry, politely "
                f"steer back to the molecule.")},
            {"role": "user", "content": question},
        ], max_tokens=500)
    except LLMUnavailable as e:
        return jsonify(error=str(e)), 503
    return jsonify(answer=answer)


_compare_cache = {}


@app.route('/api/compare', methods=['POST'])
@rate_limit(8)
def api_compare():
    data = request.get_json(silent=True) or {}
    a, b = slugify(data.get("a", "")), slugify(data.get("b", ""))
    if not (is_known(a) and is_known(b)) or a == b:
        return jsonify(error="Pick two different, known molecules."), 400
    key = tuple(sorted((a, b)))
    if key not in _compare_cache:
        try:
            _compare_cache[key] = _groq([
                {"role": "system", "content": "You are a friendly chemistry teacher."},
                {"role": "user", "content": (
                    f"Compare {a} and {b} for a school student in at most 120 words: "
                    f"structure, formula, polarity or properties, and one key difference. "
                    f"Plain text, no markdown.")},
            ], max_tokens=500)
        except LLMUnavailable as e:
            return jsonify(error=str(e)), 503
    return jsonify(answer=_compare_cache[key])


@app.route('/outputs/<path:filename>')
def serve_outputs(filename):
    return send_from_directory("outputs", filename)


if __name__ == '__main__':
    # Never enable the Werkzeug debugger on a reachable server; opt in locally.
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG") == "1",
        use_reloader=False,
    )
