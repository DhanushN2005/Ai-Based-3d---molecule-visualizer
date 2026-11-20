"""Accounts, favourites and the leaderboard (Flask blueprint).

Security notes:
- Passwords are hashed with werkzeug (scrypt); login errors never say which part was wrong.
- Sessions are signed cookies (HttpOnly, SameSite=Lax; Secure when SESSION_COOKIE_SECURE=1).
- Every state-changing account endpoint requires a CSRF token that matches the session.
- Login and registration are rate limited per IP.
"""
import hmac
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Blueprint, g, jsonify, redirect, render_template, request, session
from sqlalchemy import asc, desc, func
from werkzeug.security import check_password_hash, generate_password_hash

from models import Favorite, QuizSession, User, db
from ratelimit import allowed, rate_limit

log = logging.getLogger("chemverse")

bp = Blueprint("accounts", __name__)

USERNAME_RE = re.compile(r"^[a-z0-9_]{3,30}$")
MIN_PASSWORD, MAX_PASSWORD = 8, 128
LEADERBOARD_QUIZ_SIZE = 10          # only full-length quizzes count, so scores are comparable
LEADERBOARD_ROWS = 10

# Hash of a throwaway password: checked when the username does not exist, so the response
# time does not reveal whether an account is real.
_DUMMY_HASH = generate_password_hash("not-a-real-password")

_hooks = {"slugify": lambda s: s, "is_known": lambda s: False}


def configure(slugify, is_known):
    """main.py hands over its molecule helpers (avoids a circular import)."""
    _hooks["slugify"], _hooks["is_known"] = slugify, is_known


# ------------------------------------------------------------------- helpers
def csrf_token():
    token = session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf"] = token
    return token


def _csrf_ok():
    sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
    expected = session.get("csrf", "")
    return bool(expected) and hmac.compare_digest(str(sent), expected)


def _wants_json():
    return request.path.startswith("/api/")


def _fail(status, message, **page_ctx):
    if _wants_json():
        return jsonify(error=message), status
    return render_template("error.html", title="Request blocked", message=message), status


def csrf_protect(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not _csrf_ok():
            log.warning("CSRF check failed on %s", request.path)
            return _fail(403, "Security check failed. Reload the page and try again.")
        return fn(*a, **kw)
    return wrapper


def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if g.user is None:
            if _wants_json():
                return jsonify(error="Please log in first."), 401
            return redirect("/login?next=" + request.path)
        return fn(*a, **kw)
    return wrapper


def _safe_next(target):
    """Only allow same-site relative redirects (blocks open redirects like //evil.com)."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return "/search"


GUEST_QUIZ_KEY = "guest_quiz"        # session key: the last quiz this browser finished as a guest
GUEST_CREDIT_WINDOW = timedelta(hours=1)


def _claim_guest_quiz(user, quiz_id):
    """Credit the guest quiz this browser just finished to the account that just logged in.

    Safe because the id comes from the signed session cookie (set only by this browser's own
    finish call), the quiz must be finished and unowned, and it must be recent.
    """
    if not quiz_id:
        return
    quiz = db.session.get(QuizSession, quiz_id)
    if quiz is None or not quiz.finished or quiz.user_id is not None:
        return
    created = quiz.created_at if quiz.created_at.tzinfo else quiz.created_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - created > GUEST_CREDIT_WINDOW:
        return
    quiz.user_id = user.id
    try:
        db.session.commit()
        log.info("credited guest quiz to %s", user.username)
    except Exception:
        db.session.rollback()


def _start_session(user):
    pending = session.get(GUEST_QUIZ_KEY)    # read before the session is replaced
    session.clear()                          # new session on login: prevents session fixation
    session["uid"] = user.id
    session.permanent = True
    csrf_token()
    _claim_guest_quiz(user, pending)


@bp.before_app_request
def load_user():
    g.user = None
    uid = session.get("uid")
    if uid is not None:
        g.user = db.session.get(User, uid)
        if g.user is None:               # account deleted or stale cookie
            session.pop("uid", None)


@bp.app_context_processor
def inject_account():
    return {"csrf_token": csrf_token, "current_user": g.get("user")}


# ---------------------------------------------------------------------- auth
def _auth_page(mode, error=None, status=200, username=""):
    return render_template("auth.html", mode=mode, error=error, username=username,
                           next=_safe_next(request.values.get("next"))), status


@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return _auth_page("register")
    if not _csrf_ok():
        return _auth_page("register", "Security check failed. Reload the page and try again.", 403)
    if not allowed("register", 5, 600):
        return _auth_page("register", "Too many sign-up attempts. Please wait a few minutes.", 429)
    username = request.form.get("username", "").strip().lower()
    password = request.form.get("password", "")
    if not USERNAME_RE.match(username):
        return _auth_page("register", "Username must be 3 to 30 letters, numbers or underscores.", 400, username)
    if not (MIN_PASSWORD <= len(password) <= MAX_PASSWORD):
        return _auth_page("register", f"Password must be {MIN_PASSWORD} to {MAX_PASSWORD} characters.", 400, username)
    if User.query.filter_by(username=username).first():
        return _auth_page("register", "That username is taken.", 409, username)
    user = User(username=username, password_hash=generate_password_hash(password))
    db.session.add(user)
    try:
        db.session.commit()
    except Exception:                    # two sign-ups racing for the same name
        db.session.rollback()
        return _auth_page("register", "That username is taken.", 409, username)
    log.info("user registered: %s", username)
    _start_session(user)
    return redirect(_safe_next(request.form.get("next")))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return _auth_page("login")
    if not _csrf_ok():
        return _auth_page("login", "Security check failed. Reload the page and try again.", 403)
    if not allowed("login", 8, 60):
        return _auth_page("login", "Too many login attempts. Please wait a minute.", 429)
    username = request.form.get("username", "").strip().lower()
    password = request.form.get("password", "")
    user = User.query.filter_by(username=username).first()
    ok = check_password_hash(user.password_hash if user else _DUMMY_HASH, password)
    if not (user and ok):
        return _auth_page("login", "Invalid username or password.", 401, username)
    _start_session(user)
    return redirect(_safe_next(request.form.get("next")))


@bp.route("/logout", methods=["POST"])
@csrf_protect
def logout():
    session.clear()
    return redirect("/")


# ----------------------------------------------------------------- favourites
@bp.route("/favorites")
@login_required
def favorites_page():
    rows = Favorite.query.filter_by(user_id=g.user.id).order_by(desc(Favorite.created_at)).all()
    return render_template("favorites.html", names=[r.molecule for r in rows])


@bp.route("/api/favorites")
@login_required
def list_favorites():
    rows = Favorite.query.filter_by(user_id=g.user.id).order_by(desc(Favorite.created_at)).all()
    return jsonify(favorites=[r.molecule for r in rows])


@bp.route("/api/favorites/<name>", methods=["POST"])
@login_required
@csrf_protect
@rate_limit(60)
def toggle_favorite(name):
    key = _hooks["slugify"](name)
    if not _hooks["is_known"](key):
        return jsonify(error="Unknown molecule."), 404
    existing = Favorite.query.filter_by(user_id=g.user.id, molecule=key).first()
    if existing:
        db.session.delete(existing)
        favorite = False
    else:
        db.session.add(Favorite(user_id=g.user.id, molecule=key))
        favorite = True
    try:
        db.session.commit()
    except Exception:                    # double-click race on the unique constraint
        db.session.rollback()
        favorite = Favorite.query.filter_by(user_id=g.user.id, molecule=key).first() is not None
    return jsonify(favorite=favorite)


def is_favorite(user_id, molecule):
    return Favorite.query.filter_by(user_id=user_id, molecule=molecule).first() is not None


# ---------------------------------------------------------------- leaderboard
def leaderboard_rows(limit=LEADERBOARD_ROWS):
    """Best full-length quiz score per signed-in user, highest first (earliest player wins ties)."""
    best = func.max(QuizSession.score)
    first = func.min(QuizSession.created_at)
    rows = (
        db.session.query(User.username, best.label("best"), func.count(QuizSession.id).label("plays"))
        .join(QuizSession, QuizSession.user_id == User.id)
        .filter(QuizSession.finished.is_(True), QuizSession.total == LEADERBOARD_QUIZ_SIZE)
        .group_by(User.id, User.username)
        .order_by(desc(best), asc(first))
        .limit(limit)
        .all()
    )
    return [{"rank": i + 1, "username": r.username, "best": r.best, "plays": r.plays}
            for i, r in enumerate(rows)]


def user_best(user_id):
    return (
        db.session.query(func.max(QuizSession.score))
        .filter(QuizSession.user_id == user_id, QuizSession.finished.is_(True),
                QuizSession.total == LEADERBOARD_QUIZ_SIZE)
        .scalar()
    )


@bp.route("/leaderboard")
def leaderboard_page():
    return render_template("leaderboard.html", rows=leaderboard_rows(),
                           size=LEADERBOARD_QUIZ_SIZE, mine=user_best(g.user.id) if g.user else None)
