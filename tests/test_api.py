import re

import pytest

import main
from tests.conftest import pubchem_payload

# --------------------------------------------------------------------- pages


@pytest.mark.parametrize("path", ["/", "/search", "/quiz", "/compare", "/compare?a=water&b=ammonia",
                                  "/viewer/water", "/healthz"])
def test_pages_load(client, path):
    assert client.get(path).status_code == 200


def test_healthz_is_cheap_json(client):
    resp = client.get("/healthz")
    assert resp.get_json() == {"status": "ok"}


def test_cover_embeds_demo_molecule_and_links_to_search(client):
    html = client.get("/").get_data(as_text=True)
    assert "ChemVerse3D" in html and 'href="/search"' in html and "Caffeine" in html


@pytest.mark.parametrize("path", ["/", "/search", "/quiz", "/compare", "/viewer/water"])
def test_every_page_has_an_inline_favicon(client, path):
    # without one, browsers request /favicon.ico and log a 404 on every first visit
    assert 'rel="icon"' in client.get(path).get_data(as_text=True)


def test_viewer_shows_formula_data_for_builtin(client):
    html = client.get("/viewer/caffeine").get_data(as_text=True)
    assert "C8H10N4O2" in html
    assert 'id="legend"' in html


# ------------------------------------------------------------------ security


def test_security_headers_present(client):
    h = client.get("/").headers
    assert h["X-Content-Type-Options"] == "nosniff"
    assert h["X-Frame-Options"] == "SAMEORIGIN"
    assert "cdnjs.cloudflare.com" in h["Content-Security-Policy"]
    assert "frame-ancestors 'self'" in h["Content-Security-Policy"]
    assert h["Referrer-Policy"]


def test_cdn_script_has_integrity_hash(client):
    for path in ("/", "/viewer/water", "/quiz", "/compare"):
        html = client.get(path).get_data(as_text=True)
        tag = re.search(r'<script src="https://cdnjs[^>]*>', html).group(0)
        assert 'integrity="sha384-' in tag and 'crossorigin="anonymous"' in tag


@pytest.mark.parametrize("path", ["/outputs/../main.py", "/outputs/%2e%2e/main.py", "/viewer/..%2fmain",
                                  "/viewer/%00"])
def test_path_traversal_is_rejected(client, fake_pubchem, path):
    fake_pubchem(status=404)
    assert client.get(path).status_code == 404


def test_xss_in_molecule_name_is_not_reflected(client, fake_pubchem):
    fake_pubchem(status=404)
    resp = client.get("/viewer/<script>alert(1)</script>")
    assert b"<script>alert(1)" not in resp.data


def test_error_pages_html_for_pages_json_for_api(client):
    page = client.get("/nope")
    assert page.status_code == 404 and "text/html" in page.content_type
    api = client.get("/api/nope")
    assert api.status_code == 404 and api.get_json()["success"] is False
    assert client.post("/", data={}).status_code == 405       # old POST path is gone


# -------------------------------------------------------------------- search


def test_search_builtin_builds_files(client, tmp_path):
    data = client.post("/search", data={"molecule": "water"}).get_json()
    assert data == {"success": True, "viewer_url": "/viewer/water"}
    assert (tmp_path / "outputs" / "water.glb").exists()
    assert (tmp_path / "molecules" / "water.xyz").exists()


def test_search_empty_name_is_a_friendly_error(client):
    data = client.post("/search", data={"molecule": "  "}).get_json()
    assert data["success"] is False and "molecule name" in data["error"]


def test_pubchem_lookup_builds_caches_and_skips_network_next_time(client, fake_pubchem):
    calls = fake_pubchem(payload=pubchem_payload("C1=CC(=C(C=C1CCN)O)O"))     # dopamine
    first = client.post("/search", data={"molecule": "Dopamine"}).get_json()
    assert first["success"] and first["viewer_url"] == "/viewer/dopamine"
    assert len(calls) == 1
    with main.app.app_context():                                              # stored in the database
        row = main.db.session.get(main.CustomMolecule, "dopamine")
        assert row.smiles == "C1=CC(=C(C=C1CCN)O)O"
    assert client.post("/search", data={"molecule": "dopamine"}).get_json()["success"]
    assert len(calls) == 1                                                   # served from cache
    assert client.get("/viewer/dopamine").status_code == 200


@pytest.mark.parametrize("status,needle", [(404, "not found"), (503, "busy"), (500, "error")])
def test_pubchem_http_errors_give_clear_messages(client, fake_pubchem, status, needle):
    fake_pubchem(status=status)
    data = client.post("/search", data={"molecule": "mystery"}).get_json()
    assert data["success"] is False and needle in data["error"].lower()


def test_pubchem_unreachable(client, fake_pubchem):
    fake_pubchem(raise_exc=main.requests.ConnectionError("down"))
    data = client.post("/search", data={"molecule": "mystery"}).get_json()
    assert data["success"] is False and "reach pubchem" in data["error"].lower()


def test_pubchem_bad_or_missing_structure(client, fake_pubchem):
    fake_pubchem(payload=pubchem_payload("not a smiles((("))
    assert "read the structure" in client.post("/search", data={"molecule": "bad one"}).get_json()["error"]
    fake_pubchem(payload={"PropertyTable": {"Properties": [{}]}})
    assert "no structure" in client.post("/search", data={"molecule": "empty one"}).get_json()["error"]


def test_huge_molecules_are_refused(client, fake_pubchem):
    fake_pubchem(payload=pubchem_payload("C" * (main.MAX_HEAVY_ATOMS + 20)))
    data = client.post("/search", data={"molecule": "giant"}).get_json()
    assert data["success"] is False and "too large" in data["error"]
    assert "giant" not in main._custom


def test_pubchem_lookups_are_rate_limited(client, fake_pubchem, monkeypatch):
    fake_pubchem(status=404)
    monkeypatch.setattr(main, "PUBCHEM_LOOKUPS_PER_MIN", 5)
    out = [client.post("/search", data={"molecule": f"other{i}"}).get_json()["error"] for i in range(7)]
    assert "not found" in out[0]
    assert "Too many" in out[-1]


def test_viewer_unknown_molecule_is_html_404(client, fake_pubchem):
    fake_pubchem(status=404)
    resp = client.get("/viewer/definitely-not-real")
    assert resp.status_code == 404 and "text/html" in resp.content_type
    assert b"not found" in resp.data.lower()


def test_search_form_rate_limit(client):
    codes = [client.post("/search", data={"molecule": "water"}).status_code for _ in range(22)]
    assert codes[:20] == [200] * 20 and codes[20:] == [429, 429]


# ------------------------------------------------------------------- suggest


def test_suggest_short_query_is_empty(client):
    assert client.get("/api/suggest?q=a").get_json() == {"names": []}


def test_suggest_works_offline_with_builtin_names(client, fake_pubchem):
    fake_pubchem(raise_exc=main.requests.ConnectionError("down"))
    names = client.get("/api/suggest?q=caff").get_json()["names"]
    assert "caffeine" in names


# ---------------------------------------------------------------------- quiz


def test_quiz_questions_are_internally_consistent():
    questions = main.make_quiz(10)
    assert len(questions) == 10
    assert {q["type"] for q in questions} == {"identify", "formula", "count"}
    for q in questions:
        opts = q["options"]
        assert len(opts) == 4 and len(set(opts)) == 4
        assert 0 <= q["answer"] < 4
        correct = opts[q["answer"]]
        if q["type"] == "formula":
            name = re.search(r"formula of (.+)\?", q["text"]).group(1)
            assert correct == main._plain(name)["formula"]
        elif q["type"] == "count":
            el, name = re.search(r"How many (\w+) atoms does (.+) contain", q["text"]).groups()
            counts = main._plain(name)["counts"]
            sym = next(s for s in counts if main.PT.GetElementName(main.PT.GetAtomicNumber(s)).lower() == el)
            assert int(correct) == counts[sym]
            assert "molblock" in q
        else:
            assert q["molblock"] == main.molecule_info(correct)["molblock"]
            assert correct not in q["text"]                   # the answer is not printed in the question


@pytest.mark.parametrize("raw,expected", [("1", 3), ("100", 15), ("abc", 10), ("7", 7)])
def test_quiz_size_is_clamped(client, monkeypatch, raw, expected):
    seen = []
    monkeypatch.setattr(main, "make_quiz", lambda n: seen.append(n) or [])
    client.get(f"/api/quiz?n={raw}")
    assert seen == [expected]


# ---------------------------------------------------------------- AI endpoints


def test_ask_validation(client):
    assert client.post("/api/ask", json={"molecule": "nope", "question": "hi"}).status_code == 400
    assert client.post("/api/ask", json={"molecule": "water", "question": "   "}).status_code == 400
    assert client.post("/api/ask", data="not json").status_code == 400


def test_ask_without_api_key_degrades_gracefully(client):
    resp = client.post("/api/ask", json={"molecule": "water", "question": "Why bent?"})
    assert resp.status_code == 503 and "GROQ_API_KEY" in resp.get_json()["error"]


def test_ask_returns_answer_and_truncates_long_questions(client, monkeypatch):
    seen = {}

    def fake(messages, max_tokens=600):
        seen["q"] = messages[-1]["content"]
        return "Because of lone pairs."

    monkeypatch.setattr(main, "_groq", fake)
    resp = client.post("/api/ask", json={"molecule": "water", "question": "x" * 1000})
    assert resp.get_json() == {"answer": "Because of lone pairs."}
    assert len(seen["q"]) == 300


def test_ask_is_rate_limited_and_header_spoofing_does_not_bypass_it(client, monkeypatch):
    monkeypatch.setattr(main, "_groq", lambda *a, **k: "ok")
    codes = [client.post("/api/ask", json={"molecule": "water", "question": "hi"},
                         headers={"X-Forwarded-For": f"9.9.9.{i}"}).status_code for i in range(13)]
    assert codes[:10] == [200] * 10 and codes[10:] == [429, 429, 429]


def test_compare_api_validation_and_caching(client, monkeypatch):
    assert client.post("/api/compare", json={"a": "water", "b": "water"}).status_code == 400
    assert client.post("/api/compare", json={"a": "water", "b": "nope"}).status_code == 400
    calls = []
    monkeypatch.setattr(main, "_groq", lambda *a, **k: calls.append(1) or "They differ.")
    main._compare_cache.clear()
    assert client.post("/api/compare", json={"a": "water", "b": "ammonia"}).get_json()["answer"] == "They differ."
    assert client.post("/api/compare", json={"a": "ammonia", "b": "water"}).get_json()["answer"] == "They differ."
    assert len(calls) == 1                                    # order-independent cache


def test_compare_page_reports_unknown_molecule(client, fake_pubchem):
    fake_pubchem(status=404)
    html = client.get("/compare?a=water&b=zzzzunknown").get_data(as_text=True)
    assert "not found" in html.lower()


def test_explanation_is_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "_groq", lambda *a, **k: calls.append(1) or "Text.")
    main._explanations.pop("ozone", None)
    assert main.explain_molecule("ozone") == "Text."
    assert main.explain_molecule("ozone") == "Text."
    assert len(calls) == 1


# -------------------------------------------------------------------- frames


def test_frames_api(client):
    assert client.get("/api/frames/nope").status_code == 404
    assert client.get("/api/frames/water").get_json()["sdf"].count("$$$$") == 24
