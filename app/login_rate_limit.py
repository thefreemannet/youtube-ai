"""Persistent failed-login tracking for J3G dashboard."""

import hashlib
import sqlite3
import time

from app.dashboard_auth import DB

MAX_FAILURES = 5
WINDOW_SECONDS = 900


def _key(username, client_ip):
    value = f"{username.strip().casefold()}|{client_ip}"
    return hashlib.sha256(value.encode()).hexdigest()


def _connect():
    conn = sqlite3.connect(DB, timeout=10)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS login_attempts (
            key TEXT PRIMARY KEY,
            failures INTEGER NOT NULL,
            window_start INTEGER NOT NULL,
            blocked_until INTEGER NOT NULL
        )
    """)
    return conn


def login_is_blocked(username, client_ip):
    now = int(time.time())
    with _connect() as conn:
        row = conn.execute(
            "SELECT blocked_until FROM login_attempts WHERE key = ?",
            (_key(username, client_ip),)
        ).fetchone()
    return bool(row and row[0] > now)


def record_failure(username, client_ip):
    now = int(time.time())
    key = _key(username, client_ip)

    with _connect() as conn:
        row = conn.execute(
            "SELECT failures, window_start FROM login_attempts "
            "WHERE key = ?", (key,)
        ).fetchone()

        if row and now - row[1] < WINDOW_SECONDS:
            failures = row[0] + 1
            start = row[1]
        else:
            failures = 1
            start = now

        blocked_until = (
            now + WINDOW_SECONDS
            if failures >= MAX_FAILURES else 0
        )

        conn.execute("""
            INSERT INTO login_attempts
                (key, failures, window_start, blocked_until)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                failures=excluded.failures,
                window_start=excluded.window_start,
                blocked_until=excluded.blocked_until
        """, (key, failures, start, blocked_until))


def clear_failures(username, client_ip):
    with _connect() as conn:
        conn.execute(
            "DELETE FROM login_attempts WHERE key = ?",
            (_key(username, client_ip),)
        )
