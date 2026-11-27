"""Phase 6: disk limit, interrupted-job recovery, subtitles, cartoon approval."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.job_recovery import classify
from app.limits import ensure_free_space
from app.subtitles import write_subtitles


class LimitTests(unittest.TestCase):
    def test_disk_check_rejects_a_minimum_above_the_free_space(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                ensure_free_space(tmp, minimum=10**18)
            self.assertGreater(ensure_free_space(tmp, minimum=1), 0)


class RecoveryTests(unittest.TestCase):
    def test_classify_leaves_reviewed_and_live_jobs(self):
        self.assertEqual(classify("APPROVED", True, False, False), "leave")
        self.assertEqual(classify("PREVIEW_READY", True, False, False), "leave")
        self.assertEqual(classify("RENDERING_PREVIEW", False, True, False), "leave")
        self.assertEqual(classify("RENDERING_PREVIEW", False, False, True), "leave")

    def test_classify_marks_a_finished_preview_and_an_orphan(self):
        self.assertEqual(classify("RENDERING_PREVIEW", True, False, False), "mark_ready")
        self.assertEqual(classify("RESEARCHING", False, False, False), "mark_interrupted")

    def test_restore_writes_status_without_rebuilding_a_preview(self):
        from app.job_recovery import restore_interrupted
        with tempfile.TemporaryDirectory() as tmp:
            jobs = Path(tmp)
            ready = jobs / "20261117-010000-aaaaaa"
            orphan = jobs / "20261117-010001-bbbbbb"
            for folder, status in ((ready, "RENDERING_PREVIEW"), (orphan, "QUEUED")):
                folder.mkdir()
                (folder / "job.json").write_text(json.dumps({"status": status, "job_id": folder.name}), encoding="utf-8")
                (folder / "video_auto_preview.mp4").write_bytes(b"video")

            def complete(folder):
                return folder.name.endswith("aaaaaa")

            with patch("app.job_worker.preview_is_complete", side_effect=complete), \
                 patch("app.job_worker.upload_records_exist", return_value=False):
                notes = restore_interrupted(jobs)
            ready_job = json.loads((ready / "job.json").read_text(encoding="utf-8"))
            orphan_job = json.loads((orphan / "job.json").read_text(encoding="utf-8"))
            self.assertEqual(ready_job["status"], "PREVIEW_READY")
            self.assertEqual(orphan_job["status"], "FAILED")
            self.assertIn("Nothing was published", orphan_job["error"])
            self.assertEqual((orphan / "video_auto_preview.mp4").read_bytes(), b"video")
            self.assertEqual(len(notes), 2)


class SubtitleTests(unittest.TestCase):
    def test_cues_cover_the_narration_and_end_when_it_ends(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_subtitles(
                tmp,
                "The damper opens. Cool air enters the room. The technician checks the setpoint.",
                62.5,
            )
            text = path.read_text(encoding="utf-8")
            self.assertIn("PlayResX: 720", text)
            self.assertIn("PlayResY: 1280", text)
            self.assertIn("DejaVu Sans,28", text)
            self.assertGreaterEqual(text.count("Dialogue:"), 3)
            self.assertIn("0:00:00.00", text)
            self.assertIn("0:01:02.50", text)
            spoken = [line.rsplit(",,", 1)[-1] for line in text.splitlines() if line.startswith("Dialogue:")]
            self.assertTrue(spoken)
            self.assertTrue(all(len(line) <= 32 and "\n" not in line for line in spoken))


class CartoonApprovalTests(unittest.TestCase):
    def test_worker_accepts_a_cartoon_report_without_photographs(self):
        from app.job_worker import preview_is_complete
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "video_auto_preview.mp4").write_bytes(b"x" * 2000)
            (folder / "production_report_auto.json").write_text(json.dumps({
                "background_mode": "cartoon",
                "photographs": [],
            }), encoding="utf-8")
            with patch("app.job_worker.validate_preview", return_value={"width": 720}):
                self.assertTrue(preview_is_complete(folder))
            (folder / "production_report_auto.json").write_text(json.dumps({
                "background_mode": "cartoon",
                "photographs": ["stock.png"],
            }), encoding="utf-8")
            with patch("app.job_worker.validate_preview", return_value={"width": 720}):
                self.assertFalse(preview_is_complete(folder))

    def test_cartoon_preview_can_be_approved_by_a_person(self):
        from app.review_gate import attribution_text, review_report
        with tempfile.TemporaryDirectory() as tmp:
            jobs = Path(tmp) / "data" / "jobs"
            job_id = "20261117-105129-fdb93e"
            folder = jobs / job_id
            folder.mkdir(parents=True)
            (folder / "job.json").write_text(json.dumps({
                "status": "PREVIEW_READY",
                "topic": "How a VAV damper opens",
                "quality": {"result": "APPROVE_FOR_HUMAN_REVIEW"},
            }), encoding="utf-8")
            (folder / "narration.txt").write_text("The damper opens when the room is warm.", encoding="utf-8")
            (folder / "video_auto_preview.mp4").write_bytes(b"x" * 2000)
            (folder / "production_plan.json").write_text(json.dumps({
                "background_mode": "cartoon",
                "scenes": [{"number": 1, "heading": "Damper", "body": "The damper opens."}],
            }), encoding="utf-8")
            (folder / "production_report_auto.json").write_text(json.dumps({
                "background_mode": "cartoon",
                "photographs": [],
            }), encoding="utf-8")
            with patch("app.review_gate.JOBS", jobs):
                report = review_report(job_id)
            self.assertTrue(report["can_approve"])
            self.assertEqual(report["media"]["background_mode"], "cartoon")
            self.assertFalse(report["media"]["human_license_review_required"])
            self.assertIn("External photographs: none", attribution_text(report))
            self.assertEqual(report["blocking_issues"], [])

    def test_a_quality_revision_does_not_block_a_finished_cartoon(self):
        from app.review_gate import review_report
        with tempfile.TemporaryDirectory() as tmp:
            jobs = Path(tmp) / "data" / "jobs"
            job_id = "20261118-010000-aaaaaa"
            folder = jobs / job_id
            folder.mkdir(parents=True)
            (folder / "job.json").write_text(json.dumps({
                "status": "PREVIEW_READY",
                "topic": "Supply air reset",
                "quality": {"result": "REVISE the opening. APPROVE_FOR_HUMAN_REVIEW is not met."},
            }), encoding="utf-8")
            (folder / "narration.txt").write_text("The reset raises the supply temperature.", encoding="utf-8")
            (folder / "video_auto_preview.mp4").write_bytes(b"x" * 2000)
            (folder / "production_plan.json").write_text(json.dumps({
                "background_mode": "cartoon",
                "scenes": [{"number": 1, "heading": "Reset", "body": "The reset raises the supply temperature."}],
            }), encoding="utf-8")
            (folder / "production_report_auto.json").write_text(json.dumps({
                "background_mode": "cartoon",
                "photographs": [],
            }), encoding="utf-8")
            with patch("app.review_gate.JOBS", jobs):
                report = review_report(job_id)
            self.assertTrue(report["can_approve"])
            self.assertEqual(report["blocking_issues"], [])


if __name__ == "__main__":
    unittest.main()
