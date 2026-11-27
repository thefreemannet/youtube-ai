import tempfile
import unittest
from datetime import date
from pathlib import Path

from app.daily_slate import TOPICS, create_three_in_language, ensure_daily_slate, force_daily_slate
from app.main import get_jobs


class DailySlateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.jobs = self.root / "jobs"
        self.state = self.root / "automation" / "state.json"
        self.launched = []

    def tearDown(self):
        self.tmp.cleanup()

    def launch(self, folder, job_id):
        self.launched.append(job_id)

    def slate(self, today):
        return ensure_daily_slate(self.jobs, self.state, today, self.launch)

    def write(self, job_id, **changes):
        import json
        data = self.record(job_id)
        data.update(changes)
        (self.jobs / job_id / "job.json").write_text(json.dumps(data), encoding="utf-8")

    def topics_on(self, today):
        result = self.slate(today)
        return [self.record(job_id)["topic"] for job_id in result["waiting"]]

    def record(self, job_id):
        import json
        return json.loads((self.jobs / job_id / "job.json").read_text(encoding="utf-8"))

    def test_create_three_uses_only_the_selected_language(self):
        english = create_three_in_language(self.jobs, self.state, date(2026, 11, 21), self.launch, ["en"])
        self.assertEqual(len(english["created"]), 3)
        self.assertTrue(all(self.record(job_id)["language"] == "en" for job_id in english["created"]))
        self.assertTrue(all(self.record(job_id)["source"] == "manual" for job_id in english["created"]))
        self.assertEqual(self.launched, [english["created"][0]])
        spanish = create_three_in_language(self.jobs, self.state, date(2026, 11, 21), self.launch, ["es"])
        self.assertEqual(len(spanish["created"]), 3)
        self.assertTrue(all(self.record(job_id)["language"] == "es" for job_id in spanish["created"]))
        again = self.slate(date(2026, 11, 21))
        manual_topics = {self.record(job_id)["topic"] for job_id in english["created"]}
        added_spanish = [
            job_id for job_id in again["created"]
            if self.record(job_id)["topic"] in manual_topics and self.record(job_id)["language"] == "es" and self.record(job_id)["source"] == "automation"
        ]
        self.assertEqual(added_spanish, [])

    def test_each_day_selects_three_hvac_topics_and_starts_one(self):
        first = self.slate(date(2026, 11, 16))
        self.assertEqual(len(first["created"]), 6)
        self.assertEqual(len(first["waiting"]), 6)
        self.assertEqual(self.launched, [])
        records = [self.record(job_id) for job_id in first["created"]]
        topics = [item["topic"] for item in records]
        self.assertEqual(len(set(topics)), 3)
        self.assertTrue(all(topic in TOPICS for topic in topics))
        for topic in set(topics):
            languages = {item["language"] for item in records if item["topic"] == topic}
            self.assertEqual(languages, {"en", "es"})
        self.assertEqual(records[0]["language"], "en")
        self.assertEqual(records[1]["language"], "es")
        self.assertEqual(records[0]["topic"], records[1]["topic"])
        self.assertEqual(records[0]["status"], "SCHEDULED")
        self.assertEqual(records[1]["status"], "SCHEDULED")
        self.assertTrue(all(item["category"] == "hvac" for item in records))
        again = self.slate(date(2026, 11, 16))
        self.assertEqual(again["created"], [])
        self.assertEqual(self.launched, [])

    def test_unreviewed_videos_move_to_the_next_day(self):
        first = self.slate(date(2026, 11, 16))
        self.record(first["created"][0])
        for job_id in first["created"]:
            data = self.record(job_id)
            data["status"] = "PREVIEW_READY"
            (self.jobs / job_id / "job.json").write_text(__import__("json").dumps(data), encoding="utf-8")
        nxt = self.slate(date(2026, 11, 17))
        self.assertEqual(nxt["created"], [])
        self.assertEqual(set(nxt["moved"]), set(first["created"]))
        self.assertEqual(len(nxt["waiting"]), 6)
        for job_id in first["created"]:
            data = self.record(job_id)
            self.assertEqual(data["review_day"], "2026-11-17")
            self.assertEqual(data["slate_day"], "2026-11-16")

    def test_an_approved_video_stays_put_and_a_new_topic_fills_the_day(self):
        first = self.slate(date(2026, 11, 16))
        approved = first["created"][0]
        data = self.record(approved)
        data["status"] = "APPROVED"
        (self.jobs / approved / "job.json").write_text(__import__("json").dumps(data), encoding="utf-8")
        for job_id in first["created"][1:]:
            data = self.record(job_id)
            data["status"] = "PREVIEW_READY"
            (self.jobs / job_id / "job.json").write_text(__import__("json").dumps(data), encoding="utf-8")
        nxt = self.slate(date(2026, 11, 17))
        self.assertEqual(nxt["created"], [])
        self.assertEqual(set(nxt["moved"]), set(first["created"][1:]))
        self.assertEqual(self.record(approved)["review_day"], "2026-11-16")
        self.assertEqual(len(nxt["waiting"]), 5)
        waiting_topics = {self.record(job_id)["topic"] for job_id in nxt["waiting"]}
        self.assertIn(self.record(approved)["topic"], waiting_topics)
        self.assertEqual(len(waiting_topics), 3)

    def test_a_running_job_blocks_the_next_launch(self):
        first = self.slate(date(2026, 11, 16))
        self.slate(date(2026, 11, 16))
        self.assertEqual(self.launched, [])
        data = self.record(first["created"][0])
        data["status"] = "RENDERING_PREVIEW"
        (self.jobs / first["created"][0] / "job.json").write_text(__import__("json").dumps(data), encoding="utf-8")
        self.slate(date(2026, 11, 16))
        self.assertEqual(self.launched, [])

    def test_listing_uses_the_moved_day(self):
        from unittest.mock import patch
        first = self.slate(date(2026, 11, 16))
        self.slate(date(2026, 11, 17))
        with patch("app.main.JOBS", self.jobs):
            listed = get_jobs()
        by_id = {item["job_id"]: item for item in listed}
        carried = by_id[first["created"][1]]
        self.assertEqual(carried["day"], "November 17, 2026")
        self.assertTrue(carried["awaiting_approval"])
        self.assertTrue(carried["carried_over"])

    def test_generate_again_moves_unreviewed_videos_to_the_side(self):
        first = self.slate(date(2026, 11, 16))
        for job_id in first["created"]:
            self.write(job_id, status="PREVIEW_READY")
        forced = force_daily_slate(self.jobs, self.state, date(2026, 11, 16), self.launch)
        self.assertEqual(set(forced["parked"]), set(first["created"]))
        self.assertEqual(len(forced["created"]), 6)
        self.assertEqual(len(forced["waiting"]), 6)
        for job_id in first["created"]:
            data = self.record(job_id)
            self.assertTrue(data["parked"])
            self.assertEqual(data["review_day"], "2026-11-16")
        from unittest.mock import patch
        with patch("app.main.JOBS", self.jobs):
            listed = {item["job_id"]: item for item in get_jobs()}
        self.assertFalse(listed[first["created"][0]]["awaiting_approval"])
        self.assertEqual(listed[first["created"][0]]["day"], "November 16, 2026")
        self.assertTrue(all(listed[job_id]["awaiting_approval"] for job_id in forced["created"]))

    def test_an_english_video_gains_the_same_topic_in_spanish(self):
        import shutil
        first = self.slate(date(2026, 11, 16))
        english_topics = []
        for job_id in first["created"]:
            data = self.record(job_id)
            if data["language"] == "es":
                shutil.rmtree(self.jobs / job_id)
            else:
                english_topics.append(data["topic"])
        added = self.slate(date(2026, 11, 16))
        self.assertEqual(len(added["created"]), 3)
        for job_id in added["created"]:
            data = self.record(job_id)
            self.assertEqual(data["language"], "es")
            self.assertIn(data["topic"], english_topics)
        again = self.slate(date(2026, 11, 16))
        self.assertEqual(again["created"], [])

    def test_delete_removes_the_side_list_entry(self):
        from fastapi.testclient import TestClient
        from unittest.mock import patch
        from app.main import app
        first = self.slate(date(2026, 11, 16))
        preview_id = first["created"][1]
        self.write(preview_id, status="PREVIEW_READY")
        (self.jobs / preview_id / "video_auto_preview.mp4").write_bytes(b"preview")
        client = TestClient(app, follow_redirects=False)
        headers = {"origin": "https://testserver", "host": "testserver"}
        with patch("app.dashboard_guard.session_user", return_value="thefreemannet"), \
             patch("app.dashboard_guard.account_status", return_value="approved"), \
             patch("app.dashboard_guard.note_seen"), \
             patch("app.main.session_user", return_value="thefreemannet"), \
             patch("app.main.JOBS", self.jobs), \
             patch("app.job_worker.upload_records_exist", return_value=False):
            removed = client.delete(f"/api/jobs/{preview_id}", headers=headers)
        self.assertEqual(removed.status_code, 200)
        self.assertFalse(removed.json()["platform_copy_kept"])
        self.assertFalse((self.jobs / preview_id).exists())
        published = first["created"][0]
        with patch("app.dashboard_guard.session_user", return_value="thefreemannet"), \
             patch("app.dashboard_guard.account_status", return_value="approved"), \
             patch("app.dashboard_guard.note_seen"), \
             patch("app.main.session_user", return_value="thefreemannet"), \
             patch("app.main.JOBS", self.jobs), \
             patch("app.job_worker.upload_records_exist", return_value=True):
            removed_published = client.delete(f"/api/jobs/{published}", headers=headers)
        self.assertEqual(removed_published.status_code, 200)
        self.assertTrue(removed_published.json()["platform_copy_kept"])
        self.assertFalse((self.jobs / published).exists())

    def test_a_finished_video_does_not_start_a_daily_video(self):
        import json
        from app.daily_slate import start_next_scheduled
        self.jobs.mkdir()
        folder = self.jobs / "20261116-000000-aaaaaa"
        folder.mkdir()
        (folder / "job.json").write_text(json.dumps({
            "job_id": "20261116-000000-aaaaaa",
            "status": "SCHEDULED",
            "source": "automation",
            "created_utc": "2026-11-16T00:00:00",
            "topic": "Older daily video",
        }), encoding="utf-8")
        started = start_next_scheduled(self.jobs, self.launch, after_job_id="20261116-000009-zzzzzz")
        self.assertIsNone(started)
        self.assertEqual(self.record("20261116-000000-aaaaaa")["status"], "SCHEDULED")
        self.assertEqual(self.launched, [])

    def test_opening_the_studio_does_not_make_three_videos(self):
        import os
        from unittest.mock import patch
        from app.main import prepare_daily_slate
        env = os.environ.copy()
        env.pop("J3G_DAILY_SLATE", None)
        with patch.dict(os.environ, env, clear=True):
            self.assertIsNone(prepare_daily_slate())
        self.assertEqual(self.launched, [])

    def test_a_language_pair_continues_before_the_daily_queue(self):
        import json
        from app.daily_slate import start_next_scheduled
        self.jobs.mkdir()
        pair = "pair-both"

        def write(name, **data):
            folder = self.jobs / name
            folder.mkdir()
            data["job_id"] = name
            (folder / "job.json").write_text(json.dumps(data), encoding="utf-8")

        write(
            "20261116-000000-aaaaaa",
            status="SCHEDULED",
            source="automation",
            created_utc="2026-11-16T00:00:00",
            slate_order=0,
            topic="Older daily video",
        )
        write(
            "20261116-000001-bbbbbb",
            status="PREVIEW_READY",
            source="manual",
            pair_id=pair,
            language="en",
            created_utc="2026-11-16T01:00:00",
            slate_order=0,
            topic="Same topic",
        )
        write(
            "20261116-000002-cccccc",
            status="SCHEDULED",
            source="manual",
            pair_id=pair,
            language="es",
            created_utc="2026-11-16T01:00:01",
            slate_order=1,
            topic="Same topic",
        )
        started = start_next_scheduled(self.jobs, self.launch, after_job_id="20261116-000001-bbbbbb")
        self.assertEqual(started, "20261116-000002-cccccc")
        self.assertEqual(self.record("20261116-000000-aaaaaa")["status"], "SCHEDULED")
        self.assertEqual(self.record("20261116-000002-cccccc")["language"], "es")
        self.assertEqual(self.record("20261116-000002-cccccc")["status"], "QUEUED")

    def test_a_deleted_daily_video_stays_deleted(self):
        import shutil
        from app.daily_slate import dismiss_topic
        first = self.slate(date(2026, 11, 16))
        spanish = next(job_id for job_id in first["created"] if self.record(job_id)["language"] == "es")
        topic = self.record(spanish)["topic"]
        dismiss_topic(self.state, date(2026, 11, 16), topic, "es")
        shutil.rmtree(self.jobs / spanish)
        again = self.slate(date(2026, 11, 16))
        self.assertEqual(again["created"], [])
        self.assertNotIn(spanish, [item.name for item in self.jobs.iterdir()])
        nxt = self.slate(date(2026, 11, 17))
        revived = [
            job_id for job_id in nxt["created"]
            if self.record(job_id)["topic"] == topic and self.record(job_id)["language"] == "es"
        ]
        self.assertEqual(revived, [])
