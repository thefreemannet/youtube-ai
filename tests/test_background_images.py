import inspect
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from app.background_images import (
    assign_scenes,
    blend_background,
    compose_scene_background,
    decode_image,
    expected_background_pixel,
    load_background_config,
    prepare_plan_backgrounds,
)


DARK = (12, 20, 36)


def write_photo(folder, name, color, subjects, license_name="CC0", approved=True):
    path = Path(folder) / name
    image = Image.new("RGB", (1280, 1920), color)
    draw = ImageDraw.Draw(image)
    for band in range(12):
        shade = (band * 21) % 255
        draw.rectangle(
            (80 + band * 36, 120, 110 + band * 36, 1800),
            fill=(shade, (color[1] + shade) % 256, (color[2] + band) % 256),
        )
    image.save(path)
    metadata = {
        "approved_for_use": approved,
        "license": license_name,
        "source": "local:j3g-original-test",
        "author": "J3G",
        "title": name,
        "attribution": f"{name} — J3G — {license_name} — original test photograph",
        "subjects": subjects,
    }
    path.with_suffix(".json").write_text(json.dumps(metadata), encoding="utf-8")
    return path


class BlendTests(unittest.TestCase):
    def test_eight_percent_matches_the_blend_formula(self):
        image = Image.new("RGB", (1280, 1920), (255, 0, 0))
        blended = blend_background(image, 0.08)
        expected = expected_background_pixel((255, 0, 0), 0.08)
        self.assertEqual(blended.getpixel((0, 0)), expected)
        self.assertEqual(blended.getpixel((719, 1279)), expected)
        real = tuple(int(round(base * 0.92 + sample * 0.08)) for base, sample in zip(DARK, (255, 0, 0)))
        self.assertTrue(all(abs(a - b) <= 1 for a, b in zip(expected, real)))
        overlay = tuple((channel * 235) // 255 for channel in (255, 0, 0))
        self.assertNotEqual(expected, overlay)
        self.assertEqual(expected, (31, 18, 33))

    def test_ten_percent_matches_the_blend_formula(self):
        image = Image.new("RGB", (1600, 1600), (0, 180, 40))
        blended = blend_background(image, 0.10)
        expected = expected_background_pixel((0, 180, 40), 0.10)
        self.assertEqual(blended.getpixel((360, 640)), expected)
        real = tuple(int(round(base * 0.90 + sample * 0.10)) for base, sample in zip(DARK, (0, 180, 40)))
        self.assertTrue(all(abs(a - b) <= 1 for a, b in zip(expected, real)))
        self.assertNotEqual(blended.getpixel((360, 640)), DARK)

    def test_opacity_outside_the_allowed_range_is_rejected(self):
        image = Image.new("RGB", (1280, 1920), (255, 255, 255))
        with self.assertRaises(ValueError):
            blend_background(image, 0.50)
        with self.assertRaises(ValueError):
            blend_background(image, 0.0)


class ImageValidationTests(unittest.TestCase):
    def test_rejects_pdf_corrupt_and_unlicensed_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            pdf = folder / "manual.jpg"
            pdf.write_bytes(b"%PDF-1.7 not an image")
            with self.assertRaises(ValueError):
                decode_image(pdf)
            broken = folder / "broken.jpg"
            broken.write_bytes(b"\xff\xd8\xff" + b"not-a-jpeg" * 20)
            with self.assertRaises(ValueError):
                decode_image(broken)
            photo = write_photo(folder, "panel.png", (10, 20, 30), ["panel"], approved=False)
            plan = {"scenes": [{"number": 1, "heading": "panel", "body": "panel", "background_image": str(photo)}]}
            canvas, used = compose_scene_background(plan["scenes"][0], {"background_mode": "photo", "background_opacity": 0.08}, [folder])
            self.assertIsNone(used)
            self.assertEqual(canvas.getpixel((4, 4)), DARK)
            self.assertNotIn("background_image", plan["scenes"][0])

    def test_missing_image_keeps_the_solid_background(self):
        scene = {"number": 1, "heading": "Plain", "body": "No photograph is available."}
        canvas, used = compose_scene_background(scene, {"background_mode": "photo"}, [Path(".")])
        self.assertIsNone(used)
        self.assertEqual(canvas.getpixel((1, 1)), DARK)


class AssignmentTests(unittest.TestCase):
    def test_one_related_photo_is_used_for_the_whole_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            library = folder / "background_library"
            library.mkdir()
            write_photo(library, "drive.png", (255, 0, 0), ["variable frequency drive", "vfd panel"])
            write_photo(library, "fan.png", (0, 255, 0), ["supply fan", "electric motor"])
            Image.new("RGB", (1280, 1920), (0, 0, 255)).save(library / "flat.png")
            (library / "flat.json").write_text(json.dumps({
                "approved_for_use": True,
                "license": "CC0",
                "source": "local:j3g-original-test",
                "author": "J3G",
                "title": "flat",
                "attribution": "flat — J3G — CC0 — original test photograph",
                "subjects": ["supply fan", "electric motor"],
            }), encoding="utf-8")
            scenes = [
                {"number": 1, "heading": "Fan", "body": "The supply fan moves air."},
                {"number": 2, "heading": "Motor", "body": "The electric motor is inspected."},
            ]
            plan = {"topic": "How a supply fan and electric motor move air", "scenes": scenes}
            (folder / "visual_config.json").write_text(json.dumps({
                "background": {"mode": "photo", "opacity": 0.08, "blur_radius": 0}
            }), encoding="utf-8")
            prepare_plan_backgrounds(plan, folder, folder)
            self.assertEqual(plan["scenes"][0]["background_image"], plan["scenes"][1]["background_image"])
            self.assertTrue(plan["scenes"][0]["background_image"].endswith("shared.png"))
            first, _used = compose_scene_background(plan["scenes"][0], plan, [folder, folder / "backgrounds"])
            second, _used = compose_scene_background(plan["scenes"][1], plan, [folder, folder / "backgrounds"])
            expected = expected_background_pixel((0, 255, 0), 0.08)
            self.assertEqual(first.getpixel((8, 8)), expected)
            self.assertEqual(second.getpixel((8, 8)), expected)

    def test_same_photo_covers_every_scene_and_unrelated_video_gets_none(self):
        entries = [
            {"path": "motor.png", "metadata": {"title": "Electric motor"}, "subjects": ["electric motor"]},
        ]
        scenes = [
            {"heading": "Motor", "body": "The electric motor turns."},
            {"heading": "Again", "body": "That same electric motor is inspected."},
            {"heading": "Sky", "body": "Clouds are not equipment."},
        ]
        chosen = assign_scenes(scenes, entries, topic="electric motor")
        self.assertEqual([chosen[index]["path"] for index in range(3)], ["motor.png", "motor.png", "motor.png"])
        unrelated = assign_scenes(
            [{"heading": "Sky", "body": "Clouds are not equipment."}],
            entries,
            topic="clouds",
        )
        self.assertEqual(unrelated, {})

    def test_prepare_does_not_contact_a_network(self):
        source = inspect.getsource(prepare_plan_backgrounds)
        module = inspect.getsource(__import__("app.background_images", fromlist=["*"]))
        self.assertNotIn("httpx", module)
        self.assertNotIn("urlopen", module)
        self.assertNotIn("api.php", module)
        self.assertNotIn("urlopen", source)
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            plan = {"scenes": [{"number": 1, "heading": "Topic", "body": "No cached photograph."}]}
            with patch("socket.socket", side_effect=AssertionError("network used")):
                prepare_plan_backgrounds(plan, folder, folder)
            self.assertNotIn("background_image", plan["scenes"][0])
            self.assertEqual(plan["background_mode"], "photo")

    def test_solid_mode_removes_photographs(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "visual_config.json").write_text(json.dumps({
                "background": {"mode": "solid", "opacity": 0.08}
            }), encoding="utf-8")
            plan = {"scenes": [{
                "number": 1,
                "heading": "Keep",
                "body": "Text",
                "background_image": "old.jpg",
            }]}
            prepare_plan_backgrounds(plan, folder, folder)
            self.assertEqual(plan["background_mode"], "solid")
            self.assertEqual(plan["background_opacity"], 0)
            self.assertNotIn("background_image", plan["scenes"][0])

    def test_missing_config_defaults_to_photo_at_eight_percent(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_background_config(tmp), {"mode": "photo", "opacity": 0.08, "blur": 0.0})


class ReviewAndWorkerTests(unittest.TestCase):
    def test_optional_photo_does_not_block_approval_and_bad_license_does(self):
        from app.review_gate import review_report
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs = root / "data" / "jobs"
            job_id = "20261114-010000-b6c0de"
            folder = jobs / job_id
            folder.mkdir(parents=True)
            photo = write_photo(folder, "drive.png", (255, 0, 0), ["variable frequency drive"])
            (folder / "job.json").write_text(json.dumps({
                "status": "PREVIEW_READY",
                "topic": "Variable frequency drives",
                "quality": {"result": "APPROVE_FOR_HUMAN_REVIEW"},
            }), encoding="utf-8")
            (folder / "narration.txt").write_text("The drive controls the motor.", encoding="utf-8")
            (folder / "video_auto_preview.mp4").write_bytes(b"x" * 2000)
            scenes = [
                {
                    "number": 1,
                    "heading": "Drive",
                    "body": "The variable frequency drive panel.",
                    "background_image": str(photo),
                    "background_opacity": 0.08,
                },
                {"number": 2, "heading": "Fallback", "body": "No photograph for this scene."},
            ]
            (folder / "production_plan.json").write_text(json.dumps({
                "background_mode": "photo",
                "scenes": scenes,
            }), encoding="utf-8")
            (folder / "production_report_auto.json").write_text(json.dumps({
                "background_mode": "photo",
                "photographs": [str(photo)],
                "background_opacity": 0.08,
            }), encoding="utf-8")
            with patch("app.review_gate.JOBS", jobs):
                report = review_report(job_id)
            self.assertTrue(report["can_approve"])
            self.assertEqual(report["media"]["validated_photo_count"], 1)
            self.assertTrue(report["media"]["human_license_review_required"])
            self.assertEqual(len(report["blocking_issues"]), 0)
            bad = json.loads(photo.with_suffix(".json").read_text(encoding="utf-8"))
            bad["approved_for_use"] = False
            photo.with_suffix(".json").write_text(json.dumps(bad), encoding="utf-8")
            with patch("app.review_gate.JOBS", jobs):
                blocked = review_report(job_id)
            self.assertFalse(blocked["can_approve"])
            self.assertTrue(blocked["blocking_issues"])

    def test_solid_review_still_requires_no_photograph(self):
        from app.review_gate import review_report
        with tempfile.TemporaryDirectory() as tmp:
            jobs = Path(tmp) / "data" / "jobs"
            job_id = "20261114-010001-c0ffee"
            folder = jobs / job_id
            folder.mkdir(parents=True)
            (folder / "job.json").write_text(json.dumps({
                "status": "PREVIEW_READY",
                "topic": "Solid",
                "quality": {"result": "APPROVE_FOR_HUMAN_REVIEW"},
            }), encoding="utf-8")
            (folder / "narration.txt").write_text("Solid narration.", encoding="utf-8")
            (folder / "video_auto_preview.mp4").write_bytes(b"x" * 2000)
            (folder / "production_plan.json").write_text(json.dumps({
                "background_mode": "solid",
                "scenes": [{"number": 1, "heading": "A", "body": "B"}],
            }), encoding="utf-8")
            (folder / "production_report_auto.json").write_text(json.dumps({
                "background_mode": "solid",
                "photographs": [],
            }), encoding="utf-8")
            with patch("app.review_gate.JOBS", jobs):
                report = review_report(job_id)
            self.assertTrue(report["can_approve"])
            self.assertFalse(report["media"]["human_license_review_required"])
            self.assertEqual(set(report["fingerprints"]), {"video", "narration", "plan"})

    def test_worker_accepts_photo_and_solid_reports(self):
        from app.job_worker import preview_is_complete
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "video_auto_preview.mp4").write_bytes(b"x" * 2000)
            (folder / "production_report_auto.json").write_text(json.dumps({
                "background_mode": "photo",
                "photographs": ["drive.png"],
                "background_opacity": 0.08,
            }), encoding="utf-8")
            with patch("app.job_worker.validate_preview", return_value={"width": 720}):
                self.assertTrue(preview_is_complete(folder))
            (folder / "production_report_auto.json").write_text(json.dumps({
                "background_mode": "solid",
                "photographs": [],
                "background_opacity": 0,
            }), encoding="utf-8")
            with patch("app.job_worker.validate_preview", return_value={"width": 720}):
                self.assertTrue(preview_is_complete(folder))
            (folder / "production_report_auto.json").write_text(json.dumps({
                "background_mode": "solid",
                "photographs": ["should-not-be-here.png"],
            }), encoding="utf-8")
            with patch("app.job_worker.validate_preview", return_value={"width": 720}):
                self.assertFalse(preview_is_complete(folder))


class SlideLayerTests(unittest.TestCase):
    @unittest.skipUnless(
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf").is_file(),
        "slide fonts are installed on the application server",
    )
    def test_text_and_panels_stay_opaque_above_the_photograph(self):
        from app.production_engine_v2 import render_slides
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            photo = write_photo(folder, "drive.png", (255, 0, 0), ["drive"])
            plan = {
                "topic": "Variable frequency drives",
                "background_mode": "photo",
                "background_opacity": 0.08,
                "background_blur": 0,
                "scenes": [{
                    "number": 1,
                    "heading": "Drive panel",
                    "body": "The variable frequency drive controls the fan motor.",
                    "background_image": str(photo),
                    "background_opacity": 0.08,
                }],
            }
            render_slides(plan, folder)
            slide = Image.open(folder / "slides_auto" / "01.png")
            self.assertEqual(slide.getpixel((8, 8)), expected_background_pixel((255, 0, 0), 0.08))
            self.assertEqual(slide.getpixel((80, 340)), (23, 38, 59))
            colors = slide.getcolors(maxcolors=500000)
            present = {item[1] for item in colors}
            self.assertIn((248, 250, 252), present)
            self.assertIn((125, 211, 252), present)


if __name__ == "__main__":
    unittest.main()
