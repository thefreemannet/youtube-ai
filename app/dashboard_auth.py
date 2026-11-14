"""Server-side dashboard authentication for J3G YouTube AI."""

import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError

DB = Path(__file__).resolve().parents[1] / "data/auth/users.sqlite3"
SESSION_MAX_AGE = 8 * 60 * 60
hasher = PasswordHasher()


def authenticate(username, password):
    if not DB.is_file():
        return False
    with sqlite3.connect(DB) as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE username = ?",
            (username,)
        ).fetchone()
    if row is None:
        return False
    try:
        return bool(hasher.verify(row[0], password))
    except (VerificationError, InvalidHashError):
        return False


def create_session(username):
    if not DB.is_file():
        raise RuntimeError("Authentication database missing")

    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=SESSION_MAX_AGE)

    with sqlite3.connect(DB) as conn:
        conn.execute(
            "DELETE FROM sessions WHERE expires_utc <= ?",
            (now.isoformat(),)
        )
        conn.execute(
            "INSERT INTO sessions (token_hash, username, expires_utc) "
            "VALUES (?, ?, ?)",
            (token_hash, username, expires.isoformat())
        )
    return token


def session_user(token):
    if not token or not DB.is_file():
        return None

    token_hash = hashlib.sha256(token.encode()).hexdigest()

    with sqlite3.connect(DB) as conn:
        row = conn.execute(
            "SELECT username, expires_utc FROM sessions "
            "WHERE token_hash = ?",
            (token_hash,)
        ).fetchone()

    if row is None:
        return None

    try:
        expires = datetime.fromisoformat(row[1])
        if expires <= datetime.now(timezone.utc):
            return None
    except (TypeError, ValueError):
        return None

    return row[0]


def delete_session(token):
    if not token or not DB.is_file():
        return

    token_hash = hashlib.sha256(token.encode()).hexdigest()

    with sqlite3.connect(DB) as conn:
        conn.execute(
            "DELETE FROM sessions WHERE token_hash = ?",
            (token_hash,)
        )
