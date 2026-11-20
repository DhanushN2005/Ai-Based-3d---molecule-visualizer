"""Shared test setup. Must run before `main` is imported.

Tests never touch the real network, your Groq key, or the repo's data/ cache.
"""
import os
import tempfile

# Set before importing main: load_dotenv() does not override variables that already exist.
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="chemverse-test-")
os.environ["GROQ_API_KEY"] = ""          # real key in .env must never be used by tests
os.environ["DATABASE_URL"] = ""         # a real database in .env must never be touched (tests wipe tables)
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["TRUST_PROXY"] = "0"
os.environ["LOG_LEVEL"] = "WARNING"

import pytest  # noqa: E402

import main  # noqa: E402

# Hard stop: the tests delete rows between runs, so they may only ever run on the throwaway SQLite file.
assert main.app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:///"), "tests must not run against a real database"


class FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload if payload is not None else {}

    @property
    def ok(self):
        return 200 <= self.status_code < 400

    def json(self):
        return self._payload

    def raise_for_status(self):
        if not self.ok:
            raise main.requests.HTTPError(f"status {self.status_code}")


def pubchem_payload(smiles):
    return {"PropertyTable": {"Properties": [{"CID": 1, "SMILES": smiles, "Title": "x"}]}}


def _wipe_db():
    with main.app.app_context():
        for model in (main.accounts.Favorite, main.QuizSession, main.Explanation, main.CustomMolecule,
                      main.accounts.User):
            model.query.delete()
        main.db.session.commit()


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Fresh working dir (outputs/, molecules/), empty database, fresh rate limits and caches."""
    monkeypatch.chdir(tmp_path)
    main._hits.clear()
    _wipe_db()
    main._custom.clear()
    main._explanations.clear()
    yield
    _wipe_db()
    main._custom.clear()
    main._explanations.clear()
    main._hits.clear()


@pytest.fixture
def client():
    main.app.config["TESTING"] = True
    return main.app.test_client()


@pytest.fixture
def fake_pubchem(monkeypatch):
    """Replace network access. Usage: fake_pubchem(status=200, payload=...) or raise_exc=SomeError."""
    calls = []

    def install(status=200, payload=None, raise_exc=None):
        def fake_get(url, **kwargs):
            calls.append(url)
            if raise_exc:
                raise raise_exc
            return FakeResponse(status, payload)

        monkeypatch.setattr(main.requests, "get", fake_get)
        return calls

    return install
