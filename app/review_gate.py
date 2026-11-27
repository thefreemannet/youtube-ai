"""Local, human-in-the-loop review for J3G video previews.

This module never uploads, publishes, or changes media. Automatic checks are
metadata/integrity checks, NOT an independent factual or legal determination.
"""
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from app.background_images import validate_cached_image

ROOT = Path(os.environ.get("J3G_ROOT", "/opt/j3g-youtube-ai"))
JOBS = ROOT / "data" / "jobs"
PHOTOS = ROOT / "assets" / "photos"
JOB_PATTERN = re.compile(r"\d{8}-\d{6}-[a-f0-9]{6}\Z")
LICENSES = {"CC0", "CC0 1.0", "CC BY 2.0", "CC BY 2.5", "CC BY 3.0", "CC BY 4.0"}


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (json.JSONDecodeError, UnicodeError):
        return {}


def save_json(path, value):
    dest = path.with_name(path.name + ".tmp")
    dest.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(dest, path)


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def safe_commons_link(value):
    if not isinstance(value, str):
        return False
    parsed = urlsplit(value)
    return parsed.scheme == "https" and parsed.hostname == "commons.wikimedia.org" and not parsed.username and not parsed.password


def safe_license_link(value):
    if not isinstance(value, str):
        return False
    p = urlsplit(value)
    return p.scheme == "https" and p.hostname in {"creativecommons.org", "www.creativecommons.org"} and not p.username and not p.password


def reviewed_photo(path_text):
    """Returns a readable metadata summary plus deterministic validation errors."""
    result = {"file": Path(str(path_text)).name, "title": "", "author": "", "license": "",
              "source": "", "license_url": "", "attribution": "", "errors": []}
    photo = Path(str(path_text))
    try:
        resolved = photo.resolve(strict=True)
        if not resolved.is_relative_to(PHOTOS.resolve()) or not resolved.is_file():
            raise ValueError("Image is outside the approved photo directory")
    except (ValueError, OSError) as exc:
        result["errors"].append(str(exc))
        return result
    metadata_file = resolved.with_suffix(".json")
    metadata = read_json(metadata_file)
    if not metadata:
        result["errors"].append("Missing or invalid photo license sidecar")
        return result
    for key in ("title", "author", "license", "source", "license_url", "attribution"):
        result[key] = str(metadata.get(key) or "")[:2000]
    if metadata.get("approved_for_use") is not True:
        result["errors"].append("Image did not pass automated metadata screening")
    if result["license"] not in LICENSES:
        result["errors"].append("Unrecognized or unsupported license")
    if not safe_commons_link(result["source"]):
        result["errors"].append("Missing or invalid Wikimedia Commons source URL")
    if result["license"].startswith("CC BY"):
        if not result["author"].strip():
            result["errors"].append("Author credit is missing")
        if not safe_license_link(result["license_url"]):
            result["errors"].append("License link is missing or invalid")
    # Displayed photo is the output; no claim that visual subject itself is accurate.
    result["path"] = str(resolved)
    result["metadata_path"] = str(metadata_file)
    return result


def reviewed_background(path_text, folder):
    """Validate one optional cached background without requiring Wikimedia."""
    result = {
        "file": Path(str(path_text)).name,
        "title": "",
        "author": "",
        "license": "",
        "source": "",
        "license_url": "",
        "attribution": "",
        "errors": [],
    }
    try:
        _image, metadata, resolved = validate_cached_image(
            path_text,
            [folder, folder / "backgrounds", folder / "background_library"],
        )
    except (OSError, ValueError) as exc:
        result["errors"].append(str(exc))
        return result
    for key in ("title", "author", "license", "source", "license_url", "attribution"):
        result[key] = str(metadata.get(key) or "")[:2000]
    result["path"] = str(resolved)
    result["metadata_path"] = str(resolved.with_suffix(".json"))
    return result


def review_report(job_id):
    if not JOB_PATTERN.fullmatch(job_id):
        raise ValueError("Invalid job ID")
    folder = JOBS / job_id
    if not folder.is_dir():
        raise FileNotFoundError("Job does not exist")
    job = read_json(folder / "job.json")
    if not job:
        raise FileNotFoundError("Job data is missing")
    plan_path = folder / "production_plan.json"
    plan = read_json(plan_path)
    video = folder / "video_auto_preview.mp4"
    narration = folder / "narration_reviewed.txt"
    if not narration.is_file():
        narration = folder / "narration.txt"
    rendering = read_json(folder / "production_report_auto.json")
    scenes = plan.get("scenes") if isinstance(plan.get("scenes"), list) else []
    plan_mode = plan.get("background_mode")
    report_mode = rendering.get("background_mode")
    if plan_mode not in ("solid", "photo", "cartoon") and report_mode in ("solid", "photo", "cartoon"):
        plan_mode = report_mode
    solid = plan_mode == "solid"
    photo_mode = plan_mode == "photo"
    cartoon = plan_mode == "cartoon"
    reported_photos = rendering.get("photographs")
    if not isinstance(reported_photos, list):
        reported_photos = []
    errors = []
    # A mode flag alone must not bypass the existing photo-license checks.
    # Require a matching report generated by the renderer that was actually used.
    if solid and video.is_file() and (
        rendering.get("background_mode") != "solid"
        or reported_photos != []
    ):
        errors.append("Solid-background rendering report is missing or inconsistent")
    if photo_mode and video.is_file() and rendering.get("background_mode") != "photo":
        errors.append("Photographic background report is missing or inconsistent")
    if cartoon and video.is_file() and (
        rendering.get("background_mode") != "cartoon"
        or reported_photos != []
    ):
        errors.append("Cartoon rendering report is missing or inconsistent")
    if not video.is_file():
        errors.append("Video preview not available")
    if not narration.is_file():
        errors.append("Narration file missing")
    if not scenes:
        errors.append("Production plan or scenes missing")
    photos = []
    fingerprints = {}
    for label, path in (("video", video), ("narration", narration), ("plan", plan_path)):
        if path.is_file():
            fingerprints[label] = digest(path)
    for scene in scenes:
        num = scene.get("number")
        if photo_mode:
            image_path = scene.get("background_image")
            if not image_path:
                continue
            item = reviewed_background(image_path, folder)
            item["scene"] = num
            item["opacity"] = scene.get("background_opacity")
            if item["errors"]:
                errors.extend(f"Scene {num}: {e}" for e in item["errors"])
            photos.append(item)
            for label, path in ((f"background-{num}", Path(str(image_path))),
                                (f"background-license-{num}", Path(str(image_path)).with_suffix(".json"))):
                if path.is_file():
                    fingerprints[label] = digest(path)
            continue
        photo_path = scene.get("photo_path")
        if solid or cartoon:
            if photo_path:
                errors.append(f"Scene {num}: generated plan unexpectedly references a photograph")
            continue
        if not photo_path:
            errors.append(f"Scene {num}: missing photograph selection")
            continue
        item = reviewed_photo(photo_path)
        item["scene"] = num
        item["photo_query"] = str(scene.get("photo_query") or "")[:200]
        if item["errors"]:
            errors.extend(f"Scene {num}: {e}" for e in item["errors"])
        photos.append(item)
        for label, path in ((f"photo-{num}", Path(str(photo_path))),
                            (f"license-{num}", Path(str(photo_path)).with_suffix(".json"))):
            if path.is_file():
                fingerprints[label] = digest(path)
    if photo_mode:
        planned = [str(scene.get("background_image")) for scene in scenes if scene.get("background_image")]
        reported = rendering.get("photographs")
        if not isinstance(reported, list) or [str(item) for item in reported] != planned:
            errors.append("Background report does not match the scenes that use a photograph")
    quality = job.get("quality", {})
    quality_text = quality.get("result", "") if isinstance(quality, dict) else ""
    quality_text = str(quality_text)[:10000]
    # The Quality Agent's caution stays visible for the human. It does not
    # block approval of a finished preview. The three review confirmations do.
    decision = read_json(folder / "review_decision.json")
    decision_signature = decision.get("fingerprints")
    approval_current = bool(decision.get("decision") == "APPROVED" and decision_signature == fingerprints)
    if decision.get("decision") == "APPROVED" and not approval_current:
        errors.append("Previously approved content changed; a new review is required")
    return {
        "job_id": job_id,
        "topic": str(job.get("topic") or ""),
        "job_status": job.get("status"),
        "preview_ready": video.is_file(),
        "technical_review": {
            "agent_recommendation": quality_text,
            "independently_verified": False,
            "human_fact_check_required": True,
            "notice": "The Quality Agent does not have independent fact-checking sources. Verify factual claims against authoritative material before approval."
        },
        "media": {
            "background_mode": "solid" if solid else ("photo" if photo_mode else ("cartoon" if cartoon else "photographs")),
            "scene_count": len(scenes),
            "validated_photo_count": len(photos) - sum(bool(i["errors"]) for i in photos),
            "photos": photos,
            "automated_license_checks_passed": (
                bool(scenes and rendering.get("background_mode") == "solid"
                     and reported_photos == []
                     and not any(scene.get("photo_path") for scene in scenes))
                if solid else
                bool(scenes and rendering.get("background_mode") == "photo"
                     and isinstance(rendering.get("photographs"), list)
                     and not any(item["errors"] for item in photos)
                     and [str(scene.get("background_image")) for scene in scenes if scene.get("background_image")]
                     == [str(item) for item in reported_photos])
                if photo_mode else
                bool(scenes and rendering.get("background_mode") == "cartoon"
                     and reported_photos == []
                     and not any(scene.get("photo_path") for scene in scenes))
                if cartoon else
                bool(scenes and len(photos) == len(scenes) and not any(p["errors"] for p in photos))
            ),
            "human_license_review_required": False if cartoon else (bool(photos) if photo_mode else not solid),
            "notice": (
                "Cartoon scenes are generated for this lesson and contain no stock photographs. "
                "Review technical claims and narration before approval."
                if cartoon else
                "Solid-color backgrounds contain no third-party photographs. "
                "Review technical claims, narration, and any other third-party materials before approval."
                if solid or (photo_mode and not photos) else
                "Photographs are optional and blended at low opacity. "
                "License metadata screening is not legal clearance. Confirm attribution and depicted content before publishing."
                if photo_mode else
                "License metadata screening is not legal clearance. Confirm each file page, attribution, depicted content, and any other rights before publishing."
            ),
        },
        "blocking_issues": errors,
        "can_approve": bool(video.is_file() and narration.is_file() and scenes and not errors and job.get("status") in {"PREVIEW_READY", "AWAITING_HUMAN_REVIEW", "APPROVED"}),
        "approval_current": approval_current,
        "decision": decision.get("decision", "PENDING"),
        "reviewer_note": str(decision.get("note") or ""),
        "reviewed_utc": decision.get("reviewed_utc"),
        "fingerprints": fingerprints,
        "published": False,
    }


def decide(job_id, action, note="", confirmations=None):
    """Only records local review. No publishing or automatic re-render."""
    if action not in {"APPROVED", "CHANGES_REQUESTED"}:
        raise ValueError("Unsupported review decision")
    folder = JOBS / job_id
    report = review_report(job_id)
    job = read_json(folder / "job.json")
    if job.get("status") not in {"PREVIEW_READY", "AWAITING_HUMAN_REVIEW", "APPROVED", "CHANGES_REQUESTED"}:
        raise ValueError("This job is not ready for human review")
    if action == "APPROVED":
        if not report["can_approve"]:
            issues = [str(item) for item in report.get("blocking_issues") or [] if str(item).strip()]
            detail = "; ".join(issues) if issues else "Preview or license metadata is incomplete"
            raise ValueError(detail[:500])
        required = {"watched_video", "checked_technical_claims", "checked_media_licenses"}
        if not isinstance(confirmations, dict) or any(confirmations.get(x) is not True for x in required):
            raise ValueError("All three human review confirmations are required")
        if job.get("status") == "CHANGES_REQUESTED":
            raise ValueError("This job needs a revised preview before it can be approved")
    else:
        if len(note.strip()) < 10:
            raise ValueError("Describe requested changes (at least 10 characters)")
        if len(note) > 2000:
            raise ValueError("Review note is too long")
    decision = {
        "decision": action,
        "reviewed_utc": datetime.now(timezone.utc).isoformat(),
        "note": note.strip(),
        "confirmations": confirmations if action == "APPROVED" else {},
        "fingerprints": report["fingerprints"],
        "published": False,
    }
    save_json(folder / "review_decision.json", decision)
    job["status"] = action
    job["review_updated_utc"] = decision["reviewed_utc"]
    save_json(folder / "job.json", job)
    with (folder / "review_history.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(decision, ensure_ascii=False) + "\n")
    return {"job_id": job_id, "status": action, "published": False}


def attribution_text(report):
    photos = report["media"].get("photos") or []
    mode = report["media"].get("background_mode")
    if mode == "cartoon":
        return ("J3G YouTube AI — media attribution summary\n\n"
                "Background: generated cartoon scenes of the saved character.\n"
                "External photographs: none.\n"
                "Review technical claims and narration before publishing.\n")
    if mode == "solid" or (mode == "photo" and not photos):
        return ("J3G YouTube AI — media attribution summary\n\n"
                "Background: original solid colors and text.\n"
                "External photographs: none.\n"
                "Review any other incorporated third-party material before publishing.\n")
    if mode == "photo":
        parts = ["J3G YouTube AI — photo credit draft", ""]
        for photo in photos:
            opacity = photo.get("opacity")
            try:
                shown = f"{float(opacity):.0%}"
            except (TypeError, ValueError):
                shown = "the configured"
            parts.extend([
                f"Scene {photo['scene']}: {photo['title'] or photo['file']}",
                f"Author/credit: {photo['author'] or 'not stated'}",
                f"License: {photo['license']}",
                f"Source: {photo['source']}",
                f"Attribution: {photo['attribution']}",
                f"Adaptation: center-cropped and blended at {shown} opacity over the dark background.",
                "",
            ])
        return "\n".join(parts)
    parts = ["J3G YouTube AI — photo credit draft", "", "Review each Commons file page and license before publishing.", ""]
    for photo in report["media"]["photos"]:
        parts.extend([
            f"Scene {photo['scene']}: {photo['title']}",
            f"Author/credit: {photo['author'] or 'not stated'}",
            f"License: {photo['license']}",
            f"License URL: {photo['license_url']}",
            f"Source: {photo['source']}",
            "Adaptation: resized, cropped, darkened, and used as an 8% opacity background.",
            ""
        ])
    return "\n".join(parts)
