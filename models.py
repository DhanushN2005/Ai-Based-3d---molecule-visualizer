"""Database models. SQLite by default, any SQLAlchemy URL (for example Postgres) via DATABASE_URL."""
import os
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def _now():
    return datetime.now(timezone.utc)


def database_url(data_dir):
    """DATABASE_URL if set (Render/Heroku style postgres:// is normalised), else a SQLite file in data_dir."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        return url
    os.makedirs(data_dir, exist_ok=True)
    return "sqlite:///" + os.path.abspath(os.path.join(data_dir, "app.db")).replace("\\", "/")


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(30), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=_now, nullable=False)


class Favorite(db.Model):
    __table_args__ = (db.UniqueConstraint("user_id", "molecule", name="uq_favorite_user_molecule"),)
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    molecule = db.Column(db.String(60), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=_now, nullable=False)


class QuizSession(db.Model):
    """One quiz attempt. The answers live only here, so the browser never sees them in advance."""
    id = db.Column(db.String(36), primary_key=True)                    # uuid4: unguessable capability
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"), nullable=True, index=True)
    questions = db.Column(db.JSON, nullable=False)                     # includes "answer" and "explain"
    responses = db.Column(db.JSON, nullable=False, default=dict)       # {"0": chosen_index, ...}
    total = db.Column(db.Integer, nullable=False)
    score = db.Column(db.Integer, nullable=True)                       # set when finished
    finished = db.Column(db.Boolean, nullable=False, default=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_now, nullable=False, index=True)


class CustomMolecule(db.Model):
    """A molecule fetched from PubChem, cached so it survives restarts."""
    name = db.Column(db.String(60), primary_key=True)
    smiles = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=_now, nullable=False)


class Explanation(db.Model):
    """AI explanation cache, so the free Groq quota is spent once per molecule."""
    name = db.Column(db.String(60), primary_key=True)
    text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=_now, nullable=False)
