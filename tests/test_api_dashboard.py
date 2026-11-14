import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


class DashboardApiTests(unittest.TestCase):
    def test_dashboard_requires_login(self):
        client = TestClient(app, follow_redirects=False)
        response = client.get("/")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login")

    def test_signed_in_dashboard_isolates_the_player(self):
        client = TestClient(app, follow_redirects=False)
        with patch("app.dashboard_guard.session_user", return_value="admin"), \
             patch("app.main.session_user", return_value="admin"):
            response = client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text.count("<video"), 1)
        self.assertIn("Approve & Publish", response.text)
        self.assertNotIn('class="card"', response.text)
        self.assertIn("20261113-110306-e1d9dd", response.text)

    def test_approve_endpoint_delegates_without_removing_auth(self):
        client = TestClient(app, follow_redirects=False)
        headers = {"origin": "https://testserver", "host": "testserver"}
        body = {
            "watched_video": True,
            "checked_technical_claims": True,
            "checked_media_licenses": True,
            "publish_youtube": False,
            "publish_instagram": False,
            "confirm_publish": False,
        }
        denied = client.post("/api/jobs/20261113-110306-e1d9dd/approve-and-publish", json=body)
        self.assertEqual(denied.status_code, 401)
        with patch("app.dashboard_guard.session_user", return_value="admin"), \
             patch("app.main.session_user", return_value="admin"), \
             patch("app.approve_and_publish.approve_and_publish", return_value={"message": "recorded", "uploads": {}, "published": False}) as action:
            rejected = client.post("/api/jobs/20261113-110306-e1d9dd/approve-and-publish", json=body)
            allowed = client.post("/api/jobs/20261113-110306-e1d9dd/approve-and-publish", json=body, headers=headers)
        self.assertEqual(rejected.status_code, 403)
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.json()["message"], "recorded")
        action.assert_called_once()
        self.assertFalse(action.call_args.kwargs["publish_instagram"])
        self.assertFalse(action.call_args.kwargs["publish_youtube"])


if __name__ == "__main__":
    unittest.main()
