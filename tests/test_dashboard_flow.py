import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

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

    def test_failed_instagram_attempt_can_be_sent_again(self):
        from app.approve_and_publish import approve_and_publish
        job_id = "20261120-061940-eb046b"
        info = self.info(instagram="RECONCILIATION_REQUIRED")
        info["request_states"]["instagram"] = "RECONCILIATION_REQUIRED"
        info["retryable"] = {"youtube": False, "instagram": True}
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / job_id
            folder.mkdir()
            (folder / "job.json").write_text(json.dumps({
                "topic": "How an EMS trend log shows a heating valve that stayed open overnight",
            }), encoding="utf-8")
            (folder / "narration.txt").write_text(
                "A trend log shows the valve stayed open after the building was unoccupied.",
                encoding="utf-8",
            )
            with patch("app.approve_and_publish.JOBS", Path(tmp)), \
                 patch("app.approve_and_publish.review_report", return_value={"decision": "APPROVED", "approval_current": True}), \
                 patch("app.approve_and_publish.decide") as decide, \
                 patch("app.approve_and_publish.inspect", return_value=info), \
                 patch("app.approve_and_publish.save_metadata", return_value={}) as save, \
                 patch("app.approve_and_publish.enqueue", return_value={"request_state": "QUEUED"}) as enqueue:
                result = approve_and_publish(
                    job_id,
                    watched_video=True,
                    checked_technical_claims=True,
                    checked_media_licenses=True,
                    publish_instagram=True,
                    confirm_publish=True,
                )
        decide.assert_not_called()
        save.assert_called_once()
        enqueue.assert_called_once_with(job_id, "instagram", job_id)
        self.assertTrue(result["uploads"]["instagram"]["queued"])


class UploadRetryTests(unittest.TestCase):
    def test_unpublished_failure_can_retry_and_a_real_post_cannot(self):
        from app.publishing_workflow import archive_failed_upload, upload_retryable
        failed = {"job_id": "20261120-061940-eb046b", "state": "RECONCILIATION_REQUIRED", "published": False, "container_id": "18651092002039013"}
        self.assertTrue(upload_retryable("instagram", failed, "RECONCILIATION_REQUIRED", True))
        posted = {"state": "RECONCILIATION_REQUIRED", "published": False, "instagram_media_id": "9"}
        self.assertFalse(upload_retryable("instagram", posted, "RECONCILIATION_REQUIRED", True))
        self.assertFalse(upload_retryable("youtube", {"state": "UPLOADED_PRIVATE", "youtube_video_id": "abc"}, "COMPLETED", True))
        self.assertFalse(upload_retryable("youtube", {"state": "RECONCILIATION_REQUIRED", "upload_started": True}, "RECONCILIATION_REQUIRED", True))
        self.assertTrue(upload_retryable(
            "youtube",
            {"state": "RECONCILIATION_REQUIRED", "upload_started": True},
            "RECONCILIATION_REQUIRED",
            True,
            "RefreshError",
        ))
        self.assertFalse(upload_retryable(
            "youtube",
            {"state": "RECONCILIATION_REQUIRED", "upload_started": True, "youtube_video_id": "abc"},
            "RECONCILIATION_REQUIRED",
            True,
            "RefreshError",
        ))
        self.assertTrue(upload_retryable("youtube", {"job_id": "x", "state": "RECONCILIATION_REQUIRED"}, "RECONCILIATION_REQUIRED", True))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            records = root / "records" / "instagram"
            queues = root / "queues" / "instagram"
            records.mkdir(parents=True)
            queues.mkdir(parents=True)
            job_id = "20261120-061940-eb046b"
            (records / f"{job_id}.json").write_text(json.dumps(failed), encoding="utf-8")
            (queues / f"{job_id}.json").write_text(json.dumps({"job_id": job_id, "state": "RECONCILIATION_REQUIRED"}), encoding="utf-8")
            with patch("app.publishing_workflow.RECORDS", root / "records"), \
                 patch("app.publishing_workflow.QUEUES", root / "queues"):
                self.assertTrue(archive_failed_upload("instagram", job_id))
                self.assertFalse(archive_failed_upload("instagram", job_id))
            self.assertFalse((records / f"{job_id}.json").exists())
            self.assertEqual(len(list(records.glob(f"{job_id}.failed-*.json"))), 1)

    def test_a_stopped_upload_can_be_sent_again(self):
        from datetime import datetime, timezone
        from unittest.mock import patch
        from app.publishing_workflow import reconcile_stopped_uploads, upload_retryable
        job_id = "20261120-061940-04cb3a"
        clock = datetime(2026, 11, 21, 14, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            records = root / "records" / "instagram"
            queues = root / "queues" / "instagram"
            records.mkdir(parents=True)
            queues.mkdir(parents=True)
            (records / f"{job_id}.json").write_text(json.dumps({
                "job_id": job_id,
                "state": "CONTAINER_CREATED",
                "published": False,
                "container_id": "18651431953039013",
            }), encoding="utf-8")
            (queues / f"{job_id}.json").write_text(json.dumps({
                "job_id": job_id,
                "state": "RUNNING",
                "started_utc": "2026-11-21T13:03:14.709939+00:00",
            }), encoding="utf-8")
            fresh = "20261120-061940-eb046b"
            (records / f"{fresh}.json").write_text(json.dumps({
                "job_id": fresh, "state": "CONTAINER_CREATED", "published": False,
            }), encoding="utf-8")
            (queues / f"{fresh}.json").write_text(json.dumps({
                "job_id": fresh, "state": "RUNNING", "started_utc": "2026-11-21T13:59:30+00:00",
            }), encoding="utf-8")
            sent = "20261120-061940-823adb"
            (records / f"{sent}.json").write_text(json.dumps({
                "job_id": sent, "state": "PUBLISH_REQUESTED", "publish_sent": True,
            }), encoding="utf-8")
            (queues / f"{sent}.json").write_text(json.dumps({
                "job_id": sent, "state": "RUNNING", "worker_pid": 4242,
                "started_utc": "2026-11-21T12:00:00+00:00",
            }), encoding="utf-8")
            with patch("app.publishing_workflow.PUBLISHER", root), \
                 patch("app.publishing_workflow.RECORDS", root / "records"), \
                 patch("app.publishing_workflow.QUEUES", root / "queues"), \
                 patch("app.publishing_workflow._worker_alive", return_value=False):
                changed = reconcile_stopped_uploads(clock)
            record = json.loads((records / f"{job_id}.json").read_text(encoding="utf-8"))
            request = json.loads((queues / f"{job_id}.json").read_text(encoding="utf-8"))
            self.assertIn(f"instagram:{job_id}", changed)
            self.assertEqual(record["state"], "RECONCILIATION_REQUIRED")
            self.assertEqual(request["state"], "RECONCILIATION_REQUIRED")
            self.assertTrue(upload_retryable("instagram", record, request["state"], True))
            fresh_record = json.loads((records / f"{fresh}.json").read_text(encoding="utf-8"))
            self.assertEqual(fresh_record["state"], "CONTAINER_CREATED")
            sent_record = json.loads((records / f"{sent}.json").read_text(encoding="utf-8"))
            self.assertEqual(sent_record["state"], "RECONCILIATION_REQUIRED")
            self.assertFalse(upload_retryable("instagram", sent_record, "RECONCILIATION_REQUIRED", True))

    def test_meta_error_keeps_the_upload_reason(self):
        from app.instagram_reel_stage import checked_response

        class Response:
            ok = False
            status_code = 400

            def json(self):
                return {"debug_info": {"message": "The video file you selected is in a format that we don't support."}}

        with self.assertRaises(RuntimeError) as caught:
            checked_response(Response())
        self.assertIn("code=None", str(caught.exception))
        self.assertIn("format that we don't support", str(caught.exception))

    def test_instagram_export_copies_the_picture_instagram_already_accepts(self):
        from app.multiplatform_export import instagram_export_args
        args = instagram_export_args("preview.mp4", "ready.mp4")
        self.assertEqual(args[args.index("-c:v") + 1], "copy")
        self.assertNotIn("-use_editlist", args)
        self.assertEqual(args[args.index("-b:a") + 1], "128k")
        self.assertEqual(args[args.index("-ar") + 1], "48000")

    def test_a_rejected_reel_upload_is_tried_again_inside_the_same_request(self):
        from app.instagram_reel_stage import reel_upload_can_retry
        message = "Meta API error: HTTP 400, code=None, subcode=None. Request processing failed"
        self.assertTrue(reel_upload_can_retry(message, 0))
        self.assertTrue(reel_upload_can_retry(message, 4))
        self.assertFalse(reel_upload_can_retry(message, 5))
        self.assertFalse(reel_upload_can_retry("Meta did not return a valid container", 0))

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

    def test_a_busy_picture_request_is_asked_again(self):
        import io
        import urllib.error
        from unittest.mock import patch
        from app.cartoon_scenes import generate_image
        calls = {"n": 0}

        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return b'{"data":[{"b64_json":"aGk="}]}'

        def urlopen(request, timeout=180):
            calls["n"] += 1
            if calls["n"] == 1:
                raise urllib.error.HTTPError(
                    "https://openrouter.ai/api/v1/images",
                    402,
                    "Payment Required",
                    hdrs=None,
                    fp=io.BytesIO(b'{"error":{"message":"in_flight_budget_exhausted"}}'),
                )
            return Response()

        with patch("app.cartoon_scenes.urllib.request.urlopen", urlopen), \
             patch("app.cartoon_scenes.time.sleep"):
            picture = generate_image("a valve", "test-key")
        self.assertEqual(calls["n"], 2)
        self.assertEqual(picture, b"hi")

    def test_agent_draft_ready_requires_clear_approval(self):
        from app.job_worker import agent_draft_ready
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "narration.txt").write_text("Narration.", encoding="utf-8")
            self.assertFalse(agent_draft_ready({"quality": {"result": "REVISE the opening"}}, folder))
            self.assertTrue(agent_draft_ready({"quality": {"result": "APPROVE_FOR_HUMAN_REVIEW"}}, folder))


class SpanishTitleTests(unittest.TestCase):
    def test_a_spanish_video_gets_a_spanish_title(self):
        from app.approve_and_publish import publishing_copy
        job_id = "20261122-075722-34a006"
        topic = "Why condenser-water temperature reset saves chiller energy in cool weather"
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / job_id
            folder.mkdir()
            (folder / "job.json").write_text(json.dumps({
                "topic": topic,
                "language": "es",
                "category": "hvac",
            }), encoding="utf-8")
            (folder / "narration.txt").write_text(
                "En los sistemas de refrigeración el chiller ahorra energía.",
                encoding="utf-8",
            )
            with patch("app.approve_and_publish.JOBS", Path(tmp)):
                copy = publishing_copy(job_id)
        self.assertTrue(copy["title"].startswith("Por qué"))
        self.assertNotIn("Why condenser", copy["title"])
        self.assertLessEqual(len(copy["title"]), 100)
        self.assertTrue(copy["caption"].startswith(copy["title"]))
        self.assertIn("Explicación educativa", copy["description"])

    def test_the_studio_title_for_a_spanish_video_is_spanish(self):
        from app.spanish_titles import display_title
        topic = "What a building automation alarm does when a pump fails to prove flow"
        spanish = display_title(topic, "es", "")
        self.assertTrue(spanish.startswith("Qué hace"))
        self.assertNotIn("What a building", spanish)
        self.assertEqual(display_title(topic, "en", ""), topic)

    def test_an_english_video_keeps_its_topic_as_the_title(self):
        from app.approve_and_publish import publishing_copy
        job_id = "20261122-075722-c3e3ed"
        topic = "Why condenser-water temperature reset saves chiller energy in cool weather"
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / job_id
            folder.mkdir()
            (folder / "job.json").write_text(json.dumps({
                "topic": topic,
                "language": "en",
                "category": "hvac",
            }), encoding="utf-8")
            (folder / "narration.txt").write_text("The condenser water reset saves energy.", encoding="utf-8")
            with patch("app.approve_and_publish.JOBS", Path(tmp)):
                copy = publishing_copy(job_id)
        self.assertEqual(copy["title"], topic)


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


class TikTokPrivacyTests(unittest.TestCase):
    def test_a_public_option_is_used_and_an_unreviewed_app_stays_private(self):
        from app.tiktok_uploader import _choose_privacy
        self.assertEqual(
            _choose_privacy(["PUBLIC_TO_EVERYONE", "FOLLOWER_OF_CREATOR", "SELF_ONLY"]),
            "PUBLIC_TO_EVERYONE",
        )
        self.assertEqual(
            _choose_privacy(["FOLLOWER_OF_CREATOR", "MUTUAL_FOLLOW_FRIENDS", "SELF_ONLY"]),
            "SELF_ONLY",
        )


class TikTokHashtagTests(unittest.TestCase):
    def test_hvac_uses_the_trane_tags(self):
        from app.category_hashtags import category_hashtags, tiktok_caption
        from app.tiktok_uploader import upload_plan
        tags = category_hashtags("hvac")
        self.assertEqual(tags, ("#Trane", "#TraneTechnologies", "#HVAC", "#Automation"))
        caption = tiktok_caption("Why a trap matters", "hvac")
        self.assertTrue(caption.endswith("#Trane #TraneTechnologies #HVAC #Automation"))
        self.assertLessEqual(len(caption), 2200)
        self.assertEqual(upload_plan(4 * 1024 * 1024), (4 * 1024 * 1024, 1))
        self.assertEqual(upload_plan(70 * 1024 * 1024)[1], 7)

    def test_each_other_category_has_its_own_tags(self):
        from app.categories import CATEGORIES
        from app.category_hashtags import category_hashtags
        for item in CATEGORIES:
            tags = category_hashtags(item["id"])
            self.assertGreaterEqual(len(tags), 2)
            self.assertTrue(all(tag.startswith("#") and " " not in tag for tag in tags))
            if item["id"] != "hvac":
                self.assertNotIn("#Trane", tags)

    def test_a_finished_tiktok_post_is_not_sent_again(self):
        from app.publishing_workflow import upload_retryable
        record = {"state": "UPLOADED_PUBLIC", "tiktok_post_id": "123", "upload_started": True}
        self.assertFalse(upload_retryable("tiktok", record, "COMPLETED", True))
        failed = {"state": "FAILED", "upload_started": False}
        self.assertTrue(upload_retryable("tiktok", failed, "RECONCILIATION_REQUIRED", True))


class TikTokConnectTests(unittest.TestCase):
    def _admin(self, client_path, token_path):
        return patch.multiple(
            "app.dashboard_guard",
            session_user=lambda *_args, **_kwargs: "thefreemannet",
            account_status=lambda *_args, **_kwargs: "approved",
            note_seen=lambda *_args, **_kwargs: None,
        ), (
            patch("app.main.session_user", return_value="thefreemannet"),
            patch("app.main.is_admin", return_value=True),
            patch("app.tiktok_oauth.CLIENT_FILE", client_path),
            patch("app.tiktok_oauth.TOKEN_FILE", token_path),
        )

    def test_the_secret_is_saved_on_the_server_and_left_out_of_the_tiktok_link(self):
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app, follow_redirects=False)
        secret = "abcDEF1234567890secret"
        headers = {"origin": "https://testserver", "host": "testserver"}
        locked = client.get("/tiktok/connect")
        self.assertEqual(locked.status_code, 303)
        self.assertEqual(locked.headers["location"], "/login")
        with tempfile.TemporaryDirectory() as tmp:
            client_path = Path(tmp) / "tiktok_oauth_client.json"
            token_path = Path(tmp) / "tiktok_token.json"
            guard, patches = self._admin(client_path, token_path)
            with guard:
                for item in patches:
                    item.start()
                try:
                    denied = client.get("/tiktok/connect")
                    self.assertEqual(denied.status_code, 200)
                    self.assertIn("Client secret", denied.text)
                    bad = client.post("/tiktok/connect", headers=headers, data={
                        "client_key": "short",
                        "client_secret": secret,
                    })
                    self.assertEqual(bad.status_code, 303)
                    self.assertEqual(bad.headers["location"], "/tiktok/connect?error=invalid")
                    self.assertNotIn(secret, bad.headers["location"])
                    shown = client.get("/tiktok/connect?error=invalid")
                    self.assertIn("does not look like a TikTok credential", shown.text)
                    self.assertNotIn(secret, shown.text)
                    ok = client.post("/tiktok/connect", headers=headers, data={
                        "client_key": "awclientkey1234",
                        "client_secret": secret,
                    })
                finally:
                    for item in patches:
                        item.stop()
            self.assertEqual(ok.status_code, 303)
            location = ok.headers["location"]
            self.assertTrue(location.startswith("https://www.tiktok.com/v2/auth/authorize/?"))
            self.assertIn("client_key=awclientkey1234", location)
            self.assertIn("scope=user.info.basic%2Cvideo.publish", location)
            self.assertIn("redirect_uri=https%3A%2F%2Fyoutube-ai.lab.j3gdigital.com%2Ftiktok%2Fcallback", location)
            self.assertNotIn(secret, location)
            saved = json.loads(client_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["client_secret"], secret)
            self.assertFalse(token_path.exists())

    def test_callback_stores_the_token_only_after_the_matching_state(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.tiktok_uploader import _write_json
        client = TestClient(app, follow_redirects=False)
        with tempfile.TemporaryDirectory() as tmp:
            client_path = Path(tmp) / "tiktok_oauth_client.json"
            token_path = Path(tmp) / "tiktok_token.json"
            _write_json(client_path, {
                "client_key": "awclientkey1234",
                "client_secret": "abcDEF1234567890secret",
                "redirect_uri": "https://youtube-ai.lab.j3gdigital.com/tiktok/callback",
            })
            _write_json(client_path.with_name("tiktok_oauth_state.json"), {
                "state": "a" * 32,
                "created_utc": "2026-11-24T12:00:00+00:00",
            })
            payload = {
                "access_token": "act.exampletokenvalue",
                "refresh_token": "rft.examplerefreshvalue",
                "open_id": "openid-1",
                "scope": "user.info.basic,video.publish",
                "expires_in": 86400,
                "refresh_expires_in": 31536000,
                "token_type": "Bearer",
            }
            guard, patches = self._admin(client_path, token_path)
            with guard, patch("app.tiktok_oauth._now", return_value=datetime(2026, 11, 24, 12, 1, tzinfo=timezone.utc)):
                for item in patches:
                    item.start()
                try:
                    mismatch = client.get("/tiktok/callback?code=authcode123&state=bbbb")
                    self.assertEqual(mismatch.status_code, 303)
                    self.assertEqual(mismatch.headers["location"], "/tiktok/connect?error=failed")
                    self.assertFalse(token_path.exists())
                    response = MagicMock()
                    response.status_code = 200
                    response.json.return_value = payload
                    with patch("app.tiktok_oauth.requests.post", return_value=response) as posted:
                        matched = client.get("/tiktok/callback?code=authcode123&state=" + ("a" * 32))
                finally:
                    for item in patches:
                        item.stop()
            self.assertEqual(matched.status_code, 303)
            self.assertEqual(matched.headers["location"], "/tiktok/connect")
            posted.assert_called_once()
            sent = posted.call_args.kwargs["data"]
            self.assertEqual(sent["client_secret"], "abcDEF1234567890secret")
            self.assertNotIn("client_secret", matched.headers["location"])
            stored = json.loads(token_path.read_text(encoding="utf-8"))
            self.assertEqual(stored["access_token"], "act.exampletokenvalue")
            self.assertNotIn("client_secret", stored)
            self.assertFalse(client_path.with_name("tiktok_oauth_state.json").exists())


class LocalPicturePromptTests(unittest.TestCase):
    def test_local_pictures_do_not_receive_the_spoken_words(self):
        from app.cartoon_scenes import picture_prompt
        spoken = "Bienvenidos a su red doméstica. Hoy aprenderemos a protegerla."
        prompt = "Flat cartoon. Scene action, shown literally with simple props: " + spoken
        local = picture_prompt(prompt, paid=False)
        paid = picture_prompt(prompt, paid=True)
        self.assertNotIn("Bienvenidos", local)
        self.assertNotIn("doméstica", local)
        self.assertIn("no letters", local)
        self.assertIn("Exactly two arms", local)
        self.assertNotIn("one simple prop", local)
        self.assertEqual(paid, prompt)

    def test_paid_pictures_use_gemini_and_keep_each_scene(self):
        import json
        from unittest.mock import patch
        from app.cartoon_scenes import _request_image
        seen = {}

        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return b'{"data":[{"b64_json":"aGk="}]}'

        def urlopen(request, timeout=180):
            seen["body"] = json.loads(request.data.decode("utf-8"))
            return Response()

        spoken = "Scene action, shown literally with simple props: Bienvenidos a su red."
        with patch("app.cartoon_scenes.urllib.request.urlopen", urlopen):
            self.assertEqual(_request_image(spoken, "test-key"), b"hi")
        self.assertEqual(seen["body"]["model"], "google/gemini-2.5-flash-image")
        self.assertIn("Bienvenidos", seen["body"]["prompt"])
        self.assertEqual(seen["body"]["resolution"], "1K")
        self.assertEqual(seen["body"]["aspect_ratio"], "9:16")


if __name__ == "__main__":
    unittest.main()
