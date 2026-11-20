import json
import math
import os
import random
import re
import sys
import threading
import time
import traceback
from collections import defaultdict, deque
from functools import wraps
from urllib.parse import quote
from flask import Flask, render_template, request, jsonify, send_from_directory
from dotenv import load_dotenv

load_dotenv()  # read .env before anything reads os.environ

# Emoji in log messages crash on Windows' cp1252 when output is piped/redirected.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from rdkit import Chem, RDLogger
from rdkit.Chem import Descriptors, rdMolDescriptors
from rdkit.Geometry import Point3D

from molecules_db import MOLECULE_DB
from generate_xyz import build_molecule, write_xyz
from blender_script_gen import generate_blender_py
from export_glb_blender import run_blender_script
from glb_trimesh import build_glb
from elements import colors_for, UNKNOWN_HEX

import requests

RDLogger.DisableLog("rdApp.*")  # PubChem SMILES can be noisy; errors are handled below

app = Flask(__name__)

# Behind a host's proxy (Render, Hugging Face...) every request would look like it comes
# from the proxy's IP, so the rate limiter would treat all users as one. Only enable this
# when the app really sits behind one, otherwise clients could spoof X-Forwarded-For.
if os.environ.get("TRUST_PROXY") == "1":
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

molecule_db = MOLECULE_DB
PT = Chem.GetPeriodicTable()
MAX_HEAVY_ATOMS = int(os.environ.get("MAX_HEAVY_ATOMS", "80"))


# ------------------------------------------------------------- rate limiting
_hits = defaultdict(deque)
_hits_lock = threading.Lock()


def rate_limit(limit, window=60):
    """Allow `limit` calls per `window` seconds per client IP (in-memory, per process)."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            now = time.time()
            key = (fn.__name__, request.remote_addr)
            with _hits_lock:
                q = _hits[key]
                while q and now - q[0] > window:
                    q.popleft()
                if len(q) >= limit:
                    return jsonify(success=False, error="Too many requests. Please wait a minute."), 429
                q.append(now)
            return fn(*a, **kw)
        return wrapper
    return deco


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
        print("❌ Groq error:", e)
        raise LLMUnavailable("The AI service is unavailable right now.") from e


def explain_molecule(molecule: str) -> str:
    if molecule in _explanations:
        return _explanations[molecule]
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
    return text


# ------------------------------------------------- molecule lookup (+ PubChem)
PUBCHEM = "https://pubchem.ncbi.nlm.nih.gov/rest"
CACHE_FILE = os.path.join("data", "pubchem_cache.json")
_custom = {}  # slug -> {"smiles": ..., "title": ...}, filled from PubChem
_custom_lock = threading.Lock()


class MoleculeError(Exception):
    """A problem the user can read and act on."""


def _load_custom():
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            _custom.update({k: v for k, v in data.items()
                            if isinstance(v, dict) and isinstance(v.get("smiles"), str)})
    except (OSError, ValueError):
        pass


def _save_custom():
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(_custom, f, indent=1)


_load_custom()


def slugify(text):
    """Safe lowercase key used for molecule names AND file names (no path characters)."""
    s = re.sub(r"[^a-z0-9 \-]", "", str(text).lower())
    return re.sub(r"\s+", " ", s).strip()[:60]


def is_known(key):
    return key in molecule_db or key in _custom


def smiles_of(key):
    return molecule_db[key] if key in molecule_db else _custom[key]["smiles"]


def pubchem_lookup(query):
    """Name -> SMILES from PubChem. Raises MoleculeError with a friendly message."""
    try:
        res = requests.get(
            f"{PUBCHEM}/pug/compound/name/{quote(query, safe='')}/property/SMILES,Title/JSON",
            timeout=15,
            headers={"User-Agent": "chemverse3d"},
        )
    except requests.RequestException:
        raise MoleculeError("Could not reach PubChem. Check your internet connection.")
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
    except Exception:
        raise MoleculeError(f"Could not build a 3D structure for '{key}'.")
    with _custom_lock:
        _custom[key] = {"smiles": smiles, "title": key}
        try:
            _save_custom()
        except OSError:
            print("⚠️ Could not write the PubChem cache file.")
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
        print("⚠️ trimesh export failed, falling back to Blender:")
        traceback.print_exc()
        try:
            run_blender_script(generate_blender_py(mol, name))
        except Exception:
            print("❌ Blender fallback failed too:")
            traceback.print_exc()
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


# -------------------------------------------------------------------- routes
@rate_limit(20)
def _build_from_form():
    try:
        name = resolve_molecule(request.form.get('molecule', ''))
        mol = get_mol(name)  # one conformer for everything
        write_xyz(mol, name)
        if ensure_glb(name, mol, force=True):
            print(f"✅ File created: outputs/{name}.glb")
        # The viewer draws from RDKit data, so it works even without a GLB.
        return jsonify(success=True, viewer_url=f"/viewer/{quote(name)}")
    except MoleculeError as e:
        return jsonify(success=False, error=str(e))
    except Exception:
        print("❌ Error:")
        traceback.print_exc()
        return jsonify(success=False, error="Something went wrong building that molecule.")


@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        return _build_from_form()
    return render_template('index.html', molecules=sorted(molecule_db))


@app.route('/viewer/<molecule>')
def viewer(molecule):
    try:
        name = resolve_molecule(molecule)  # also lets shared PubChem links work
    except MoleculeError as e:
        return render_template("error.html", message=str(e)), 404
    info = molecule_info(name)
    has_glb = ensure_glb(name, get_mol(name)) is not None
    return render_template(
        "viewer.html",
        molecule=name,
        info=info,
        has_glb=has_glb,
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


@app.route('/api/quiz')
@rate_limit(30)
def api_quiz():
    try:
        n = max(3, min(int(request.args.get("n", 10)), 15))
    except ValueError:
        n = 10
    return jsonify(questions=make_quiz(n))


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
