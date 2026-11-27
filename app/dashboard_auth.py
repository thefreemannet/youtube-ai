"""Server-side dashboard authentication for J3G YouTube AI."""

import hashlib
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError

DB = Path(os.environ.get("J3G_AUTH_DB") or Path(__file__).resolve().parents[1] / "data" / "auth" / "users.sqlite3")
SESSION_MAX_AGE = 8 * 60 * 60
ADMIN_USERNAME = "thefreemannet"
USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{2,31}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
hasher = PasswordHasher()

_EXTRA_COLUMNS = {
    "display_name": "TEXT NOT NULL DEFAULT ''",
    "email": "TEXT NOT NULL DEFAULT ''",
    "role": "TEXT NOT NULL DEFAULT 'user'",
    "status": "TEXT NOT NULL DEFAULT 'approved'",
    "created_utc": "TEXT NOT NULL DEFAULT ''",
    "last_login_utc": "TEXT NOT NULL DEFAULT ''",
    "last_seen_utc": "TEXT NOT NULL DEFAULT ''",
    "login_count": "INTEGER NOT NULL DEFAULT 0",
    "videos_created": "INTEGER NOT NULL DEFAULT 0",
}


def _now():
    return datetime.now(timezone.utc)


def _iso(moment=None):
    return (moment or _now()).isoformat()


def _parse(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


@contextmanager
def connect():
    if not DB.is_file():
        raise FileNotFoundError("Authentication database missing")
    conn = sqlite3.connect(DB, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        _ensure_schema(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            expires_utc TEXT NOT NULL
        )
        """
    )
    existing = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
    for name, declaration in _EXTRA_COLUMNS.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE users ADD COLUMN {name} {declaration}")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS account_activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            kind TEXT NOT NULL,
            created_utc TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "UPDATE users SET role = 'admin', status = 'approved' WHERE username = ?",
        (ADMIN_USERNAME,),
    )
    conn.commit()


def _row(username):
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        return dict(row) if row else None


def authenticate(username, password):
    """True only when the password matches an approved account."""
    return check_login(username, password) == "approved"


def check_login(username, password):
    """Return approved, pending, rejected, or invalid."""
    if not DB.is_file() or not username or not password:
        return "invalid"
    try:
        row = _row(username)
    except FileNotFoundError:
        return "invalid"
    if row is None:
        return "invalid"
    try:
        verified = hasher.verify(row["password_hash"], password)
    except (VerificationError, InvalidHashError):
        return "invalid"
    if not verified:
        return "invalid"
    status = row["status"] or "approved"
    if status in {"approved", "pending", "rejected"}:
        return status
    return "invalid"


def account_status(username):
    if not username or not DB.is_file():
        return "missing"
    try:
        row = _row(username)
    except FileNotFoundError:
        return "missing"
    if row is None:
        return "missing"
    return row["status"] or "approved"


def is_admin(username):
    if username != ADMIN_USERNAME or not DB.is_file():
        return False
    try:
        row = _row(username)
    except FileNotFoundError:
        return False
    return bool(row and row["role"] == "admin" and (row["status"] or "approved") == "approved")


def register_account(name, username, email, password):
    display_name = " ".join(str(name or "").split())
    account = str(username or "").strip()
    address = str(email or "").strip().lower()
    secret = str(password or "")
    if not 2 <= len(display_name) <= 80:
        raise ValueError("Name must be 2 to 80 characters.")
    if account.casefold() == ADMIN_USERNAME:
        raise ValueError("That username is not available.")
    if not USERNAME_RE.fullmatch(account):
        raise ValueError("Choose a username of 3 to 32 letters or numbers.")
    if not EMAIL_RE.fullmatch(address) or len(address) > 120:
        raise ValueError("Enter a valid email address.")
    if not 8 <= len(secret) <= 200:
        raise ValueError("Password must be 8 to 200 characters.")
    with connect() as conn:
        taken = conn.execute("SELECT username, email FROM users").fetchall()
        for existing in taken:
            if existing["username"].casefold() == account.casefold():
                raise ValueError("That username is already registered.")
            if existing["email"] and existing["email"].casefold() == address:
                raise ValueError("That email is already registered.")
        conn.execute(
            """
            INSERT INTO users (
                username, password_hash, display_name, email, role, status,
                created_utc, last_login_utc, last_seen_utc, login_count, videos_created
            ) VALUES (?, ?, ?, ?, 'user', 'pending', ?, '', '', 0, 0)
            """,
            (account, hasher.hash(secret), display_name, address, _iso()),
        )
        conn.commit()
    return account


def record_login(username):
    if not username or not DB.is_file():
        return
    moment = _iso()
    with connect() as conn:
        conn.execute(
            """
            UPDATE users
            SET last_login_utc = ?, last_seen_utc = ?,
                login_count = COALESCE(login_count, 0) + 1
            WHERE username = ?
            """,
            (moment, moment, username),
        )
        if username != ADMIN_USERNAME:
            conn.execute(
                "INSERT INTO account_activity (username, kind, created_utc) VALUES (?, 'login', ?)",
                (username, moment),
            )
        conn.commit()


def note_seen(username):
    if not username or username == ADMIN_USERNAME or not DB.is_file():
        return
    try:
        row = _row(username)
    except FileNotFoundError:
        return
    if row is None or (row["status"] or "") != "approved":
        return
    seen = _parse(row["last_seen_utc"])
    moment = _now()
    if seen and moment - seen < timedelta(seconds=45):
        return
    with connect() as conn:
        conn.execute(
            "UPDATE users SET last_seen_utc = ? WHERE username = ?",
            (_iso(moment), username),
        )
        conn.commit()


def record_video(username):
    if not username or username == ADMIN_USERNAME or not DB.is_file():
        return
    moment = _iso()
    try:
        with connect() as conn:
            conn.execute(
                """
                UPDATE users
                SET videos_created = COALESCE(videos_created, 0) + 1
                WHERE username = ? AND status = 'approved'
                """,
                (username,),
            )
            if conn.execute("SELECT changes()").fetchone()[0]:
                conn.execute(
                    "INSERT INTO account_activity (username, kind, created_utc) VALUES (?, 'video', ?)",
                    (username, moment),
                )
            conn.commit()
    except FileNotFoundError:
        return


def set_account_status(username, status):
    if status not in {"approved", "rejected"}:
        raise ValueError("Unsupported account status")
    account = str(username or "")
    if not USERNAME_RE.fullmatch(account):
        raise LookupError("Account not found")
    if account.casefold() == ADMIN_USERNAME:
        raise ValueError("The administrator account cannot be changed here.")
    with connect() as conn:
        row = conn.execute(
            "SELECT username, role FROM users WHERE username = ?",
            (account,),
        ).fetchone()
        if row is None or row["role"] == "admin":
            raise LookupError("Account not found")
        conn.execute(
            "UPDATE users SET status = ? WHERE username = ?",
            (status, account),
        )
        conn.commit()


def _recent(moment, row_value, window):
    seen = _parse(row_value)
    return bool(seen and moment - seen <= window)


def account_overview():
    moment = _now()
    week_start = _iso(moment - timedelta(days=7))
    with connect() as conn:
        rows = [dict(item) for item in conn.execute(
            """
            SELECT username, display_name, email, status, created_utc,
                   last_login_utc, last_seen_utc, login_count, videos_created
            FROM users
            WHERE username != ?
            ORDER BY created_utc DESC, username COLLATE NOCASE
            """,
            (ADMIN_USERNAME,),
        ).fetchall()]
        videos_week = conn.execute(
            """
            SELECT COUNT(*) FROM account_activity
            WHERE kind = 'video' AND created_utc >= ? AND username != ?
            """,
            (week_start, ADMIN_USERNAME),
        ).fetchone()[0]
        logins_week = conn.execute(
            """
            SELECT COUNT(*) FROM account_activity
            WHERE kind = 'login' AND created_utc >= ? AND username != ?
            """,
            (week_start, ADMIN_USERNAME),
        ).fetchone()[0]
    users = []
    for row in rows:
        users.append({
            "username": row["username"],
            "name": row["display_name"] or row["username"],
            "email": row["email"] or "",
            "status": row["status"] or "approved",
            "created_utc": row["created_utc"] or "",
            "last_login_utc": row["last_login_utc"] or "",
            "last_seen_utc": row["last_seen_utc"] or "",
            "login_count": int(row["login_count"] or 0),
            "videos_created": int(row["videos_created"] or 0),
            "activity": activity_label(row["last_seen_utc"], row["last_login_utc"], moment),
        })
    return {
        "approved": sum(item["status"] == "approved" for item in users),
        "pending": sum(item["status"] == "pending" for item in users),
        "active_now": sum(item["activity"] == "Active" for item in users),
        "active_today": sum(
            _recent(moment, item["last_seen_utc"] or item["last_login_utc"], timedelta(days=1))
            for item in users
        ),
        "logged_in_7d": sum(
            _recent(moment, item["last_login_utc"], timedelta(days=7))
            for item in users
        ),
        "videos_week": int(videos_week or 0),
        "logins_week": int(logins_week or 0),
        "never_signed_in": sum(not item["last_login_utc"] for item in users),
        "users": users,
    }


def activity_label(last_seen, last_login, moment=None):
    moment = moment or _now()
    seen = _parse(last_seen) or _parse(last_login)
    if seen is None:
        return "Never"
    elapsed = moment - seen
    if elapsed <= timedelta(minutes=15):
        return "Active"
    if elapsed <= timedelta(days=1):
        return "Active today"
    return "Inactive"


def create_session(username):
    if not DB.is_file():
        raise RuntimeError("Authentication database missing")

    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = _now()
    expires = now + timedelta(seconds=SESSION_MAX_AGE)

    with connect() as conn:
        conn.execute(
            "DELETE FROM sessions WHERE expires_utc <= ?",
            (now.isoformat(),)
        )
        conn.execute(
            "INSERT INTO sessions (token_hash, username, expires_utc) VALUES (?, ?, ?)",
            (token_hash, username, expires.isoformat()),
        )
        conn.commit()
    return token


def session_user(token):
    if not token or not DB.is_file():
        return None

    token_hash = hashlib.sha256(token.encode()).hexdigest()

    try:
        with connect() as conn:
            found = conn.execute(
                "SELECT username, expires_utc FROM sessions WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()
            row = dict(found) if found else None
    except FileNotFoundError:
        return None

    if row is None:
        return None

    expires = _parse(row["expires_utc"])
    if expires is None or expires <= _now():
        return None
    return row["username"]


def delete_session(token):
    if not token or not DB.is_file():
        return

    token_hash = hashlib.sha256(token.encode()).hexdigest()

    try:
        with connect() as conn:
            conn.execute(
                "DELETE FROM sessions WHERE token_hash = ?",
                (token_hash,),
            )
            conn.commit()
    except FileNotFoundError:
        return
