import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.dashboard_auth import (
    ADMIN_USERNAME,
    account_overview,
    activity_label,
    check_login,
    hasher,
    is_admin,
    note_seen,
    record_video,
    register_account,
)
from app.dashboard_page import render_dashboard
from app.main import app


ORIGIN = {"origin": "https://testserver", "host": "testserver"}


class AccountFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "users.sqlite3"
        self.db.write_bytes(b"")
        self.db_patch = patch("app.dashboard_auth.DB", self.db)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.addCleanup(self.tmp.cleanup)
        self.client = TestClient(app, follow_redirects=False)
        from app.dashboard_auth import connect
        with connect() as conn:
            conn.execute("DELETE FROM users")
            conn.execute(
                """
                INSERT INTO users (
                    username, password_hash, display_name, email, role, status, created_utc
                ) VALUES (?, ?, 'Admin', 'thefreemannet@j3gdigital.com', 'admin', 'approved', '2026-11-16T00:00:00+00:00')
                """,
                (ADMIN_USERNAME, hasher.hash("admin-pass-123")),
            )
            conn.commit()

    def test_login_page_links_to_create_account(self):
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Create an account", response.text)
        self.assertIn('href="/register"', response.text)
        register = self.client.get("/register")
        self.assertIn("approves", register.text.lower())
        self.assertIn('name="email"', register.text)

    def test_new_account_waits_for_the_administrator(self):
        created = self.client.post("/register", data={
            "name": "Ada Lovelace",
            "username": "ada",
            "email": "ada@example.com",
            "password": "correct-horse",
            "confirm": "correct-horse",
        })
        self.assertEqual(created.status_code, 303)
        self.assertEqual(created.headers["location"], "/waiting")
        self.assertEqual(check_login("ada", "correct-horse"), "pending")
        overview = account_overview()
        self.assertEqual(overview["pending"], 1)
        self.assertEqual(overview["approved"], 0)
        self.assertEqual(overview["users"][0]["activity"], "Never")

        with patch("app.dashboard_guard.session_user", return_value="ada"):
            home = self.client.get("/")
            blocked = self.client.post("/api/jobs", json={"topic": "How does a damper work?"}, headers=ORIGIN)
        self.assertEqual(home.status_code, 303)
        self.assertEqual(home.headers["location"], "/waiting")
        self.assertEqual(blocked.status_code, 403)

    def test_only_the_administrator_can_approve_and_see_activity(self):
        register_account("Ada Lovelace", "ada", "ada@example.com", "correct-horse")
        with patch("app.dashboard_guard.session_user", return_value="ada"), \
             patch("app.dashboard_guard.account_status", return_value="approved"), \
             patch("app.dashboard_guard.note_seen"):
            hidden = self.client.get("/accounts")
        self.assertEqual(hidden.status_code, 303)
        self.assertEqual(hidden.headers["location"], "/")

        with patch("app.dashboard_guard.session_user", return_value=ADMIN_USERNAME):
            page = self.client.get("/accounts")
            approved = self.client.post("/accounts/ada/approve", headers=ORIGIN)
        self.assertEqual(page.status_code, 200)
        self.assertIn("Accounts and activity", page.text)
        self.assertIn("Ada Lovelace", page.text)
        self.assertIn("pending", page.text)
        self.assertIn(">Approve<", page.text)
        self.assertEqual(approved.status_code, 303)
        self.assertEqual(check_login("ada", "correct-horse"), "approved")

        note_seen("ada")
        record_video("ada")
        overview = account_overview()
        self.assertEqual(overview["approved"], 1)
        self.assertEqual(overview["active_now"], 1)
        self.assertEqual(overview["videos_week"], 1)
        self.assertEqual(overview["users"][0]["activity"], "Active")
        self.assertTrue(is_admin(ADMIN_USERNAME))
        self.assertFalse(is_admin("ada"))

        with patch("app.dashboard_guard.session_user", return_value=ADMIN_USERNAME):
            self.client.post("/accounts/ada/reject", headers=ORIGIN)
        self.assertEqual(check_login("ada", "correct-horse"), "rejected")
        denied = self.client.post("/login", data={"username": "ada", "password": "correct-horse"})
        self.assertEqual(denied.status_code, 403)
        self.assertIn("not approved", denied.text)

    def test_reserved_admin_name_and_dashboard_link(self):
        with self.assertRaises(ValueError):
            register_account("Freeman", "thefreemannet", "other@example.com", "correct-horse")
        plain = render_dashboard([], "Online", {"youtube": False, "instagram": False})
        admin = render_dashboard([], "Online", {"youtube": False, "instagram": False}, is_admin=True)
        self.assertNotIn('href="/accounts"', plain)
        self.assertIn('href="/accounts"', admin)
        self.assertEqual(activity_label("", "", __import__("datetime").datetime.now(__import__("datetime").timezone.utc)), "Never")
