import re

import pytest

import main
from models import database_url
from tests.conftest import pubchem_payload

# ------------------------------------------------------------------ helpers


def token(client):
    """CSRF token for this client's session (a GET creates the session)."""
    client.get("/login")
    with client.session_transaction() as s:
        return s["csrf"]


def signup(client, username="alice", password="correct horse", **extra):
    data = {"username": username, "password": password, "csrf_token": token(client), **extra}
    return client.post("/register", data=data)


def login(client, username="alice", password="correct horse", **extra):
    data = {"username": username, "password": password, "csrf_token": token(client), **extra}
    return client.post("/login", data=data)


def csrf_headers(client):
    return {"X-CSRF-Token": token(client)}


def logged_in_client(username="alice"):
    c = main.app.test_client()
    assert signup(c, username).status_code == 302
    return c


def board():
    with main.app.app_context():
        return main.accounts.leaderboard_rows()


@pytest.fixture
def fake_quiz(monkeypatch):
    """Cheap quiz questions so these tests do not build 3D molecules."""
    def make(n):
        return [{"type": "formula", "text": f"question {i}", "options": ["a", "b", "c", "d"],
                 "answer": i % 4, "explain": f"explanation {i}", "molblock": "BIG", "colors": {}}
                for i in range(n)]
    monkeypatch.setattr(main, "make_quiz", make)


def play(client, n=10, correct=None, headers=None, user_headers=True):
    """Start a quiz, answer `correct` questions right (rest wrong), finish. Returns (quiz_id, finish_json)."""
    started = client.get(f"/api/quiz?n={n}").get_json()
    qid = started["quiz_id"]
    with main.app.app_context():
        answers = [q["answer"] for q in main.db.session.get(main.QuizSession, qid).questions]
    correct = n if correct is None else correct
    for i, right in enumerate(answers):
        choice = right if i < correct else (right + 1) % 4
        assert client.post(f"/api/quiz/{qid}/answer", json={"question": i, "choice": choice}).status_code == 200
    return qid, client.post(f"/api/quiz/{qid}/finish").get_json()


# ------------------------------------------------------------- registration


def test_register_creates_account_logs_in_and_hashes_password(client):
    resp = signup(client, "Alice", "correct horse")
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/search")
    with client.session_transaction() as s:
        assert s["uid"]
    with main.app.app_context():
        user = main.accounts.User.query.one()
        assert user.username == "alice"                       # normalised to lower case
        assert "correct horse" not in user.password_hash and ":" in user.password_hash


@pytest.mark.parametrize("username,password,needle", [
    ("ab", "correct horse", "3 to 30"),
    ("bad name!", "correct horse", "3 to 30"),
    ("x" * 31, "correct horse", "3 to 30"),
    ("alice", "short", "Password must be"),
    ("alice", "x" * 200, "Password must be"),
])
def test_register_validation(client, username, password, needle):
    resp = signup(client, username, password)
    assert resp.status_code == 400 and needle in resp.get_data(as_text=True)


def test_register_rejects_duplicate_usernames_case_insensitively(client):
    assert signup(client, "alice").status_code == 302
    other = main.app.test_client()
    assert signup(other, "ALICE").status_code == 409


def test_register_requires_csrf_token(client):
    client.get("/register")
    resp = client.post("/register", data={"username": "alice", "password": "correct horse"})
    assert resp.status_code == 403
    resp = client.post("/register", data={"username": "alice", "password": "correct horse", "csrf_token": "forged"})
    assert resp.status_code == 403
    with main.app.app_context():
        assert main.accounts.User.query.count() == 0


def test_register_is_rate_limited(client):
    codes = [signup(client, f"user{i}").status_code for i in range(7)]
    assert 429 in codes and codes[0] == 302


# --------------------------------------------------------------------- login


def test_login_success_and_wrong_password_look_the_same_as_unknown_user(client):
    signup(main.app.test_client(), "alice")
    bad_pw = login(client, "alice", "wrong password!")
    no_user = login(client, "nobody", "wrong password!")
    assert bad_pw.status_code == no_user.status_code == 401
    msg = "Invalid username or password."
    assert msg in bad_pw.get_data(as_text=True) and msg in no_user.get_data(as_text=True)
    assert login(client).status_code == 302


def test_login_is_rate_limited(client):
    signup(main.app.test_client(), "alice")
    codes = [login(client, "alice", "nope nope nope").status_code for _ in range(10)]
    assert codes[:8] == [401] * 8 and codes[8:] == [429, 429]


def test_login_requires_csrf(client):
    signup(main.app.test_client(), "alice")
    resp = client.post("/login", data={"username": "alice", "password": "correct horse"})
    assert resp.status_code == 403


@pytest.mark.parametrize("target,expected", [
    ("/favorites", "/favorites"),
    ("//evil.example", "/search"),
    ("https://evil.example", "/search"),
    ("/\\evil.example", "/search"),
])
def test_login_redirect_is_same_site_only(client, target, expected):
    signup(main.app.test_client(), "alice")
    resp = login(client, next=target)
    assert resp.status_code == 302 and resp.headers["Location"] == expected


def test_login_starts_a_fresh_session(client):
    signup(main.app.test_client(), "alice")
    before = token(client)
    login(client)
    with client.session_transaction() as s:
        assert s["csrf"] != before and "uid" in s            # no session fixation


def test_session_cookie_flags(client):
    cookie = client.get("/login").headers.get("Set-Cookie", "")
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie


def test_logout_needs_post_and_csrf():
    c = logged_in_client()
    assert c.get("/logout").status_code == 405
    assert c.post("/logout").status_code == 403
    with c.session_transaction() as s:
        assert "uid" in s                                     # still logged in
    resp = c.post("/logout", data={"csrf_token": token(c)})
    assert resp.status_code == 302
    with c.session_transaction() as s:
        assert "uid" not in s


def test_pages_show_login_state():
    anon = main.app.test_client()
    assert "Log in" in anon.get("/").get_data(as_text=True)
    c = logged_in_client()
    html = c.get("/viewer/water").get_data(as_text=True)
    assert "alice" in html and "Log out" in html


# ----------------------------------------------------------------- favourites


def test_favorites_require_login(client):
    assert client.get("/api/favorites").status_code == 401
    assert client.post("/api/favorites/water").status_code == 401
    page = client.get("/favorites")
    assert page.status_code == 302 and "/login?next=/favorites" in page.headers["Location"]


def test_favorite_toggle_needs_csrf_and_known_molecule():
    c = logged_in_client()
    assert c.post("/api/favorites/water").status_code == 403
    assert c.post("/api/favorites/not-a-molecule", headers=csrf_headers(c)).status_code == 404


def test_favorite_toggle_and_list():
    c = logged_in_client()
    h = csrf_headers(c)
    assert c.post("/api/favorites/water", headers=h).get_json() == {"favorite": True}
    assert c.post("/api/favorites/Caffeine", headers=h).get_json() == {"favorite": True}
    assert c.get("/api/favorites").get_json()["favorites"] == ["caffeine", "water"]
    assert "Saved to favourites" in c.get("/viewer/water").get_data(as_text=True)
    assert c.post("/api/favorites/water", headers=h).get_json() == {"favorite": False}
    assert c.get("/api/favorites").get_json()["favorites"] == ["caffeine"]
    page = c.get("/favorites").get_data(as_text=True)
    assert "/viewer/caffeine" in page and "/viewer/water" not in page


def test_favorites_are_private_per_user():
    a, b = logged_in_client("alice"), logged_in_client("bobby")
    a.post("/api/favorites/water", headers=csrf_headers(a))
    assert b.get("/api/favorites").get_json()["favorites"] == []
    assert "Save to favourites" in b.get("/viewer/water").get_data(as_text=True)


def test_pubchem_molecules_can_be_favourited(fake_pubchem):
    fake_pubchem(payload=pubchem_payload("C1=CC(=C(C=C1CCN)O)O"))
    c = logged_in_client()
    c.post("/search", data={"molecule": "dopamine"})
    assert c.post("/api/favorites/dopamine", headers=csrf_headers(c)).get_json() == {"favorite": True}


# ---------------------------------------------------- quiz: server-side scoring


def test_quiz_api_never_sends_answers_or_explanations(client, fake_quiz):
    data = client.get("/api/quiz?n=5").get_json()
    assert re.fullmatch(r"[0-9a-f-]{36}", data["quiz_id"])
    for q in data["questions"]:
        assert "answer" not in q and "explain" not in q
    assert data["signed_in"] is False


def test_answer_endpoint_checks_on_the_server(client, fake_quiz):
    qid = client.get("/api/quiz?n=4").get_json()["quiz_id"]
    ok = client.post(f"/api/quiz/{qid}/answer", json={"question": 0, "choice": 0}).get_json()
    assert ok == {"correct": True, "answer": 0, "explain": "explanation 0"}
    bad = client.post(f"/api/quiz/{qid}/answer", json={"question": 1, "choice": 3}).get_json()
    assert bad["correct"] is False and bad["answer"] == 1


def test_answer_endpoint_validation(client, fake_quiz):
    qid = client.get("/api/quiz?n=4").get_json()["quiz_id"]
    url = f"/api/quiz/{qid}/answer"
    assert client.post(url, json={"question": 0, "choice": 0}).status_code == 200
    assert client.post(url, json={"question": 0, "choice": 1}).status_code == 409      # no changing answers
    assert client.post(url, json={"question": 9, "choice": 0}).status_code == 400
    assert client.post(url, json={"question": 1, "choice": 7}).status_code == 400
    assert client.post(url, json={"question": -1, "choice": 0}).status_code == 400
    assert client.post(url, json={"question": "x", "choice": 0}).status_code == 400
    assert client.post(url, json={}).status_code == 400
    assert client.post("/api/quiz/does-not-exist/answer", json={"question": 0, "choice": 0}).status_code == 404


def test_finish_computes_the_score_itself_and_ignores_client_claims(client, fake_quiz):
    qid = client.get("/api/quiz?n=10").get_json()["quiz_id"]
    for i in range(10):
        client.post(f"/api/quiz/{qid}/answer", json={"question": i, "choice": (i + 1) % 4})   # all wrong
    result = client.post(f"/api/quiz/{qid}/finish", json={"score": 10, "total": 10}).get_json()
    assert result["score"] == 0 and result["total"] == 10 and result["answered"] == 10


def test_unanswered_questions_count_as_wrong_and_finish_is_idempotent(client, fake_quiz):
    qid = client.get("/api/quiz?n=5").get_json()["quiz_id"]
    client.post(f"/api/quiz/{qid}/answer", json={"question": 0, "choice": 0})
    first = client.post(f"/api/quiz/{qid}/finish").get_json()
    assert first["score"] == 1 and first["answered"] == 1
    assert client.post(f"/api/quiz/{qid}/finish").get_json() == first
    assert client.post(f"/api/quiz/{qid}/answer", json={"question": 1, "choice": 1}).status_code == 409
    assert client.post("/api/quiz/nope/finish").status_code == 404


def test_finished_quiz_drops_the_heavy_3d_data(client, fake_quiz):
    qid, _ = play(client, n=3)
    with main.app.app_context():
        row = main.db.session.get(main.QuizSession, qid)
        assert row.finished and all("molblock" not in q for q in row.questions)


def test_quiz_is_linked_to_the_signed_in_user():
    c = logged_in_client()
    assert c.get("/api/quiz?n=3").get_json()["signed_in"] is True
    with main.app.app_context():
        assert main.QuizSession.query.one().user_id == main.accounts.User.query.one().id


def test_old_unfinished_quizzes_are_pruned(client, fake_quiz):
    from datetime import datetime, timedelta, timezone
    old = client.get("/api/quiz?n=3").get_json()["quiz_id"]
    with main.app.app_context():
        row = main.db.session.get(main.QuizSession, old)
        row.created_at = datetime.now(timezone.utc) - timedelta(days=2)
        main.db.session.commit()
    client.get("/api/quiz?n=3")                                # starting a new quiz prunes
    with main.app.app_context():
        assert main.db.session.get(main.QuizSession, old) is None


# ---------------------------------------------------------------- leaderboard


def test_leaderboard_ranks_best_score_per_signed_in_user(fake_quiz):
    alice, bobby = logged_in_client("alice"), logged_in_client("bobby")
    play(alice, correct=6)
    play(alice, correct=9)                                     # alice's best is 9, played twice
    play(bobby, correct=7)
    rows = board()
    assert [(r["rank"], r["username"], r["best"], r["plays"]) for r in rows] == [
        (1, "alice", 9, 2), (2, "bobby", 7, 1)]
    html = alice.get("/leaderboard").get_data(as_text=True)
    assert "alice" in html and "9 / 10" in html and "Your best" in html


def test_leaderboard_ignores_guests_and_short_quizzes(fake_quiz):
    guest = main.app.test_client()
    play(guest, n=10, correct=10)                              # guest: not listed
    alice = logged_in_client("alice")
    play(alice, n=3, correct=3)                                # 3-question quiz: not comparable
    assert board() == []
    assert "No scores yet" in guest.get("/leaderboard").get_data(as_text=True)


def test_leaderboard_ties_go_to_the_earlier_player(fake_quiz):
    first, second = logged_in_client("first"), logged_in_client("second")
    play(first, correct=8)
    play(second, correct=8)
    assert [r["username"] for r in board()] == ["first", "second"]


def test_finish_reports_the_players_best(fake_quiz):
    c = logged_in_client()
    play(c, correct=4)
    _, result = play(c, correct=7)
    assert result["best"] == 7 and result["on_leaderboard"] is True
    _, short = play(c, n=3, correct=3)
    assert short["on_leaderboard"] is False


# --------------------------------------------------------- persistence / config


def test_pubchem_molecules_survive_a_restart(client, fake_pubchem):
    fake_pubchem(payload=pubchem_payload("C1=CC(=C(C=C1CCN)O)O"))
    client.post("/search", data={"molecule": "dopamine"})
    main._custom.clear()                                       # simulate a fresh process
    assert not main.is_known("dopamine")
    main._load_custom()
    assert main.is_known("dopamine")


def test_explanations_survive_a_restart(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "_groq", lambda *a, **k: calls.append(1) or "Stored text.")
    assert main.explain_molecule("ozone") == "Stored text."
    main._explanations.clear()                                 # simulate a fresh process
    assert main.explain_molecule("ozone") == "Stored text."
    assert len(calls) == 1


def test_oversized_request_bodies_are_rejected(client):
    resp = client.post("/api/ask", data="x" * 70_000, content_type="application/json")
    assert resp.status_code == 413 and resp.get_json()["success"] is False


def test_database_url_normalises_postgres_scheme(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "postgres://user:pw@host/db")
    assert database_url(str(tmp_path)) == "postgresql://user:pw@host/db"
    monkeypatch.delenv("DATABASE_URL")
    assert database_url(str(tmp_path)).startswith("sqlite:///") and (tmp_path / "").exists()


# ------------------------------------------------ crediting a guest's last quiz


def owner_of(qid):
    with main.app.app_context():
        return main.db.session.get(main.QuizSession, qid).user_id


def username_of(user_id):
    with main.app.app_context():
        return main.db.session.get(main.accounts.User, user_id).username


def test_guest_quiz_is_credited_when_registering_right_after(fake_quiz):
    guest = main.app.test_client()
    qid, _ = play(guest, correct=7)
    assert owner_of(qid) is None
    assert signup(guest, "carol").status_code == 302
    assert username_of(owner_of(qid)) == "carol"
    assert [(r["username"], r["best"]) for r in board()] == [("carol", 7)]


def test_guest_quiz_is_credited_when_logging_in_to_an_existing_account(fake_quiz):
    signup(main.app.test_client(), "dave")
    guest = main.app.test_client()
    qid, _ = play(guest, correct=5)
    assert login(guest, "dave").status_code == 302
    assert username_of(owner_of(qid)) == "dave"


def test_a_different_browser_cannot_claim_someone_elses_guest_quiz(fake_quiz):
    qid, _ = play(main.app.test_client(), correct=10)           # guest A finishes a quiz
    attacker = main.app.test_client()                           # browser B never played it
    assert signup(attacker, "mallory").status_code == 302
    assert owner_of(qid) is None and board() == []


def test_only_finished_quizzes_are_credited(fake_quiz):
    guest = main.app.test_client()
    qid = guest.get("/api/quiz?n=10").get_json()["quiz_id"]     # started, never finished
    signup(guest, "erin")
    assert owner_of(qid) is None


def test_only_the_last_guest_quiz_is_credited(fake_quiz):
    guest = main.app.test_client()
    first, _ = play(guest, correct=3)
    second, _ = play(guest, correct=9)
    signup(guest, "frank")
    assert owner_of(first) is None
    assert username_of(owner_of(second)) == "frank"


def test_old_guest_quizzes_are_not_credited(fake_quiz):
    from datetime import datetime, timedelta, timezone
    guest = main.app.test_client()
    qid, _ = play(guest, correct=8)
    with main.app.app_context():
        row = main.db.session.get(main.QuizSession, qid)
        row.created_at = datetime.now(timezone.utc) - timedelta(hours=3)
        main.db.session.commit()
    signup(guest, "gina")
    assert owner_of(qid) is None


def test_a_quiz_that_already_has_an_owner_is_never_reassigned(fake_quiz):
    alice = logged_in_client("alice")
    qid, _ = play(alice, correct=10)
    owner = owner_of(qid)
    thief = main.app.test_client()
    thief.get("/login")
    with thief.session_transaction() as s:
        s[main.accounts.GUEST_QUIZ_KEY] = qid                   # even with the id in their own cookie
    signup(thief, "henry")
    assert owner_of(qid) == owner


def test_credit_is_one_time_and_signed_in_players_do_not_leave_a_claim_behind(fake_quiz):
    guest = main.app.test_client()
    play(guest, correct=6)
    signup(guest, "ivy")
    with guest.session_transaction() as s:
        assert main.accounts.GUEST_QUIZ_KEY not in s            # consumed by the new session
    play(guest, correct=6)                                      # now signed in
    with guest.session_transaction() as s:
        assert main.accounts.GUEST_QUIZ_KEY not in s


def test_quiz_page_prompts_guests_but_not_signed_in_players():
    guest_html = main.app.test_client().get("/quiz").get_data(as_text=True)
    assert "playing as a guest" in guest_html and "/register?next=/quiz" in guest_html
    assert "/register?next=/leaderboard" in guest_html          # prompt shown after finishing
    assert "playing as a guest" not in logged_in_client().get("/quiz").get_data(as_text=True)
