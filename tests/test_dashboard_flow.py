import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.dashboard_page import render_dashboard


class DashboardPageTests(unittest.TestCase):
    def test_one_player_and_no_stacked_cards(self):
        jobs = []
        for job_id, topic in (
            ("20261110-225615-919b89", "What is BACnet and how does it help HVAC technicians?"),
            ("20261111-021504-ab7c1a", "How does a VAV box work in an HVAC system?"),
            ("20261113-110306-e1d9dd", "How does a Variable Frequency Drive save energy?"),
        ):
            jobs.append({
                "job_id": job_id,
                "topic": topic,
                "status": "PREVIEW_READY",
                "duration": 63.67,
                "error": "",
                "preview_ready": True,
                "video_ready": False,
                "day": "November 13, 2026",
                "youtube_state": "NOT_UPLOADED",
                "youtube_request": "NOT_REQUESTED",
                "instagram_state": "NOT_UPLOADED",
                "instagram_request": "NOT_REQUESTED",
            })
        html = render_dashboard(jobs, "Application Online — Publishing Enabled (YouTube, Instagram)", {
            "youtube": True,
            "instagram": True,
        })
        self.assertEqual(html.count("<video"), 1)
        self.assertNotIn('class="card"', html)
        self.assertIn("Approve & Publish", html)
        self.assertIn("Download video", html)
        self.assertEqual(html.count('id="download-video"'), 1)
        self.assertIn("20261110-225615-919b89", html)
        self.assertIn("20261111-021504-ab7c1a", html)
        self.assertIn("20261113-110306-e1d9dd", html)
        self.assertIn("Create a video", html)
        self.assertIn("Video history", html)

    def test_topic_cannot_break_out_of_json(self):
        html = render_dashboard([{
            "job_id": "20261113-110306-e1d9dd",
            "topic": "</script><script>alert(1)</script>",
            "status": "FAILED",
            "duration": None,
            "error": "<b>bad</b>",
            "preview_ready": False,
            "video_ready": False,
            "day": "November 13, 2026",
            "youtube_state": "NOT_UPLOADED",
            "youtube_request": "NOT_REQUESTED",
            "instagram_state": "NOT_UPLOADED",
            "instagram_request": "NOT_REQUESTED",
        }], "Online <b>", {"youtube": False, "instagram": False})
        self.assertNotIn("</script><script>", html)
        self.assertIn("Online &lt;b&gt;", html)
        self.assertNotIn("Online <b>", html)


class ApproveAndPublishTests(unittest.TestCase):
    def info(self, youtube="NOT_UPLOADED", instagram="NOT_UPLOADED"):
        return {
            "export_ready": True,
            "metadata_ready": {"youtube": True, "instagram": True},
            "platform_states": {"youtube": youtube, "instagram": instagram},
            "request_states": {"youtube": "NOT_REQUESTED", "instagram": "NOT_REQUESTED"},
        }

    def test_locked_bacnet_job_is_not_touched(self):
        from app.approve_and_publish import approve_and_publish
        with patch("app.approve_and_publish.decide") as decide, patch("app.approve_and_publish.enqueue") as enqueue:
            with self.assertRaises(ValueError):
                approve_and_publish(
                    "20261110-225615-919b89",
                    watched_video=True,
                    checked_technical_claims=True,
                    checked_media_licenses=True,
                    publish_youtube=True,
                    confirm_publish=True,
                )
        decide.assert_not_called()
        enqueue.assert_not_called()

    def test_missing_confirmation_does_not_approve(self):
        from app.approve_and_publish import approve_and_publish
        with patch("app.approve_and_publish.decide") as decide:
            with self.assertRaises(ValueError):
                approve_and_publish(
                    "20261113-120000-aabbcc",
                    watched_video=True,
                    checked_technical_claims=False,
                    checked_media_licenses=True,
                )
        decide.assert_not_called()

    def test_youtube_only_does_not_queue_instagram(self):
        from app.approve_and_publish import approve_and_publish
        job_id = "20261113-120000-aabbcc"
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / job_id
            folder.mkdir()
            (folder / "job.json").write_text(json.dumps({
                "topic": "How a condensate trap protects an air handler",
            }), encoding="utf-8")
            (folder / "narration.txt").write_text(
                "A trap keeps sewer gas out of the air handler and lets condensate leave.",
                encoding="utf-8",
            )
            with patch("app.approve_and_publish.JOBS", Path(tmp)), \
                 patch("app.approve_and_publish.review_report", return_value={"decision": "PENDING", "approval_current": False}), \
                 patch("app.approve_and_publish.decide", return_value={"status": "APPROVED"}) as decide, \
                 patch("app.approve_and_publish.inspect", return_value=self.info()), \
                 patch("app.approve_and_publish.save_metadata", return_value={}) as save, \
                 patch("app.approve_and_publish.enqueue", return_value={"request_state": "QUEUED"}) as enqueue:
                result = approve_and_publish(
                    job_id,
                    watched_video=True,
                    checked_technical_claims=True,
                    checked_media_licenses=True,
                    publish_youtube=True,
                    publish_instagram=False,
                    confirm_publish=True,
                )
        decide.assert_called_once()
        save.assert_called_once()
        self.assertEqual(save.call_args.args[1], "youtube")
        enqueue.assert_called_once_with(job_id, "youtube", job_id)
        self.assertTrue(result["uploads"]["youtube"]["queued"])
        self.assertNotIn("instagram", result["uploads"])

    def test_existing_upload_is_not_retried(self):
        from app.approve_and_publish import approve_and_publish
        job_id = "20261113-120000-aabbcc"
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / job_id
            folder.mkdir()
            (folder / "job.json").write_text(json.dumps({"topic": "How a condensate trap protects an air handler"}), encoding="utf-8")
            (folder / "narration.txt").write_text("Condensate must leave through a trap.", encoding="utf-8")
            with patch("app.approve_and_publish.JOBS", Path(tmp)), \
                 patch("app.approve_and_publish.review_report", return_value={"decision": "APPROVED", "approval_current": True}), \
                 patch("app.approve_and_publish.decide") as decide, \
                 patch("app.approve_and_publish.inspect", return_value=self.info(youtube="UPLOADED_PRIVATE")), \
                 patch("app.approve_and_publish.save_metadata") as save, \
                 patch("app.approve_and_publish.enqueue") as enqueue:
                result = approve_and_publish(
                    job_id,
                    watched_video=True,
                    checked_technical_claims=True,
                    checked_media_licenses=True,
                    publish_youtube=True,
                    confirm_publish=True,
                )
        decide.assert_not_called()
        save.assert_not_called()
        enqueue.assert_not_called()
        self.assertTrue(result["uploads"]["youtube"]["skipped"])

    def test_rejects_another_videos_caption(self):
        from app.approve_and_publish import approve_and_publish
        job_id = "20261113-120000-aabbcc"
        borrowed = "What is BACnet, and how does it help HVAC technicians? Learn the fundamentals of BACnet."
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / job_id
            folder.mkdir()
            (folder / "job.json").write_text(json.dumps({"topic": "How a condensate trap protects an air handler"}), encoding="utf-8")
            (folder / "narration.txt").write_text("A trap protects the air handler.", encoding="utf-8")
            other = root / "20261110-225615-919b89"
            other.mkdir()
            (other / "instagram_publish_metadata.json").write_text(json.dumps({"caption": borrowed}), encoding="utf-8")
            with patch("app.approve_and_publish.JOBS", root), patch("app.approve_and_publish.decide") as decide:
                with self.assertRaises(ValueError):
                    approve_and_publish(
                        job_id,
                        watched_video=True,
                        checked_technical_claims=True,
                        checked_media_licenses=True,
                        publish_instagram=True,
                        confirm_publish=True,
                        caption=borrowed,
                    )
        decide.assert_not_called()


class MediaValidateTests(unittest.TestCase):
    def test_rejects_empty_file(self):
        from app.media_validate import validate_preview
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            name = handle.name
        with self.assertRaises(ValueError):
            validate_preview(name)
        Path(name).unlink()

    def test_requires_vertical_frame_and_audio(self):
        from app.media_validate import validate_preview
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            handle.write(b"x" * 1200)
            name = handle.name
        payload = {
            "streams": [
                {"codec_type": "video", "width": 1280, "height": 720},
                {"codec_type": "audio"},
            ],
            "format": {"duration": "12.0"},
        }
        with patch("app.media_validate.subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = json.dumps(payload)
            run.return_value.stderr = ""
            with self.assertRaises(ValueError):
                validate_preview(name)
        Path(name).unlink()


class JobWorkerGuardTests(unittest.TestCase):
    def test_upload_record_blocks_rerun(self):
        from app.job_worker import upload_records_exist
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("app.job_worker.PUBLISHER", root):
                self.assertFalse(upload_records_exist("20261113-110306-e1d9dd"))
                record = root / "upload_records" / "youtube"
                record.mkdir(parents=True)
                (record / "20261113-110306-e1d9dd.json").write_text("{}", encoding="utf-8")
                self.assertTrue(upload_records_exist("20261113-110306-e1d9dd"))

    def test_agent_draft_ready_requires_clear_approval(self):
        from app.job_worker import agent_draft_ready
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "narration.txt").write_text("Narration.", encoding="utf-8")
            self.assertFalse(agent_draft_ready({"quality": {"result": "REVISE the opening"}}, folder))
            self.assertTrue(agent_draft_ready({"quality": {"result": "APPROVE_FOR_HUMAN_REVIEW"}}, folder))


class TopicSpellingTests(unittest.TestCase):
    def test_bacnet_topic_replaces_basnet(self):
        from app.workflow_dashboard import preserve_topic_terms
        fixed = preserve_topic_terms(
            "talk about the bacnet wiring",
            "Welcome to BASnet wiring. BAS-net uses a trunk. BACnet MS/TP is separate.",
        )
        self.assertNotIn("BASnet", fixed)
        self.assertNotIn("BAS-net", fixed)
        self.assertIn("BACnet wiring", fixed)
        self.assertEqual(fixed.count("BACnet"), 3)

    def test_other_topics_are_left_alone(self):
        from app.workflow_dashboard import preserve_topic_terms
        original = "This sentence mentions BASnet only as a quoted mistake."
        self.assertEqual(preserve_topic_terms("How a condensate trap works", original), original)


if __name__ == "__main__":
    unittest.main()
