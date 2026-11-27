"""Record one human approval, then queue only the platforms that were selected.

This module does not talk to YouTube or Instagram directly. Uploads stay in the
existing YouTube and explicit-Instagram workers. A video that already
received a platform id is never sent again. A failed attempt with no id can be.
"""

import json

from app.categories import category_info
from app.dashboard_publisher import enqueue
from app.publishing_workflow import inspect, prepare, save_metadata
from app.review_gate import JOBS, decide, review_report
from app.spanish_titles import spanish_title

# Already uploaded. Approval records and upload records for this job stay as they are.
LOCKED_JOBS = {"20261110-225615-919b89"}
PLATFORMS = ("youtube", "instagram")


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, ValueError):
        return {}


def _foreign_bodies(job_id):
    """Exact descriptions and captions that belong to a different video."""
    banned = set()
    if not JOBS.is_dir():
        return banned
    for folder in JOBS.iterdir():
        if not folder.is_dir() or folder.name == job_id:
            continue
        for name in ("youtube_publish_metadata.json", "instagram_publish_metadata.json"):
            data = _read_json(folder / name)
            for key in ("description", "caption"):
                text = str(data.get(key) or "").strip()
                if len(text) >= 40:
                    banned.add(text)
    return banned


def publishing_copy(job_id, title="", description="", caption=""):
    """Build YouTube and Instagram text from this job only."""
    folder = JOBS / job_id
    job = _read_json(folder / "job.json")
    topic = " ".join(str(job.get("topic") or "").split())
    if not topic:
        raise ValueError("This job has no topic to generate publishing text from")
    narration_path = folder / "narration_reviewed.txt"
    if not narration_path.is_file():
        narration_path = folder / "narration.txt"
    narration = ""
    if narration_path.is_file():
        narration = " ".join(narration_path.read_text(encoding="utf-8").split())
    spanish = str(job.get("language") or "").lower() == "es"
    if spanish:
        title = spanish_title(topic, narration)[:100]
        note = "Explicación educativa. No sustituye el manual del equipo ni las normas aplicables."
    else:
        title = topic[:100]
        note = category_info(job.get("category")).get("publishing_note") or "An educational explanation."
    generated = {
        "title": title,
        "description": f"{title}\n\n{narration}\n\n{note}".strip(),
        "caption": f"{title}\n\n{narration}".strip()[:2200],
    }
    limits = {"title": 100, "description": 5000, "caption": 2200}
    supplied = {"title": title, "description": description, "caption": caption}
    chosen = {}
    for key, limit in limits.items():
        text = str(supplied[key] or "").strip() or generated[key]
        if "DRAFT:" in text.upper():
            raise ValueError("Remove draft notices from the publishing text before approval")
        if not 1 <= len(text) <= limit:
            raise ValueError(f"{key.title()} length is outside the allowed range")
        chosen[key] = text
    banned = _foreign_bodies(job_id)
    for key in ("description", "caption"):
        if chosen[key] in banned:
            raise ValueError("Publishing text matches another video. Write text for this video only")
    return chosen


def _open_platforms(info):
    open_platforms = []
    skipped = {}
    for platform in PLATFORMS:
        state = str(info["platform_states"].get(platform) or "")
        request_state = str(info["request_states"].get(platform) or "")
        retryable = info.get("retryable", {}).get(platform) is True
        if (state == "NOT_UPLOADED" and request_state == "NOT_REQUESTED") or retryable:
            open_platforms.append(platform)
            continue
        skipped[platform] = {
            "queued": False,
            "skipped": True,
            "state": state,
            "request_state": request_state,
            "message": "An upload record or request already exists. It was not retried.",
        }
    return open_platforms, skipped


def _ensure_prepared(job_id):
    info = inspect(job_id)
    ready = (
        info.get("export_ready") is True
        and info.get("metadata_ready", {}).get("youtube") is True
        and info.get("metadata_ready", {}).get("instagram") is True
    )
    if ready:
        return info
    if any(info.get("platform_states", {}).get(platform) != "NOT_UPLOADED" for platform in PLATFORMS):
        raise ValueError(
            "Publishing files are incomplete and an upload record already exists. "
            "Reconcile that record before another upload."
        )
    prepared = prepare(job_id)
    if "platform_states" in prepared:
        return prepared
    return inspect(job_id)


def approve_and_publish(
    job_id,
    *,
    watched_video,
    checked_technical_claims,
    checked_media_licenses,
    publish_youtube=False,
    publish_instagram=False,
    publish_tiktok=False,
    confirm_publish=False,
    title="",
    description="",
    caption="",
):
    """Approve the selected video and queue only the platforms named by the admin."""
    if job_id in LOCKED_JOBS:
        raise ValueError("This video was already uploaded and must not be published again")
    if not (watched_video is True and checked_technical_claims is True and checked_media_licenses is True):
        raise ValueError(
            "Confirm that you watched the video, checked the technical claims, and verified content rights"
        )
    selected = []
    if publish_youtube is True:
        selected.append("youtube")
    if publish_instagram is True:
        selected.append("instagram")
    if publish_tiktok is True:
        selected.append("tiktok")
    if selected and confirm_publish is not True:
        raise ValueError("Confirm publishing before any upload is queued")
    copy = publishing_copy(job_id, title, description, caption) if selected else None

    report = review_report(job_id)
    if report.get("job_status") == "CHANGES_REQUESTED":
        raise ValueError("This job needs a revised preview before it can be approved")
    already = report.get("decision") == "APPROVED" and report.get("approval_current") is True
    if not already:
        decide(
            job_id,
            "APPROVED",
            confirmations={
                "watched_video": True,
                "checked_technical_claims": True,
                "checked_media_licenses": True,
            },
        )
    result = {
        "job_id": job_id,
        "video_approval": "already_current" if already else "recorded",
        "uploads": {},
        "published": False,
    }
    if not selected:
        result["message"] = "Video approval recorded. No platform was selected, so nothing was uploaded."
        return result

    info = _ensure_prepared(job_id)
    open_now, skipped = _open_platforms(info)
    for platform in selected:
        if platform == "tiktok":
            continue
        if platform in skipped:
            result["uploads"][platform] = skipped[platform]
            continue
        if platform not in open_now:
            result["uploads"][platform] = {
                "queued": False,
                "skipped": True,
                "message": "This platform is not open for a new upload.",
            }
            continue
        save_metadata(
            job_id,
            platform,
            title=copy["title"],
            description=copy["description"],
            caption=copy["caption"],
            confirm_technical=True,
            confirm_credits=True,
        )
        queued = enqueue(job_id, platform, job_id)
        result["uploads"][platform] = {
            "queued": True,
            "skipped": False,
            "request_state": queued.get("request_state", "QUEUED"),
            "message": "Upload queued.",
        }
    if "tiktok" in selected:
        from app.publishing_workflow import PUBLISHER, config
        token_file = PUBLISHER / "credentials" / "tiktok_token.json"
        tiktok_on = config().get("publishing_enabled") is True and config().get("platforms", {}).get("tiktok", {}).get("enabled") is True
        connected = tiktok_on and token_file.is_file() and not (token_file.stat().st_mode & 0o077)
        state = str(info.get("platform_states", {}).get("tiktok") or "NOT_UPLOADED")
        request_state = str(info.get("request_states", {}).get("tiktok") or "NOT_REQUESTED")
        retryable = info.get("retryable", {}).get("tiktok") is True
        if not connected:
            result["uploads"]["tiktok"] = {
                "queued": False,
                "skipped": True,
                "message": "TikTok account is not connected",
            }
        elif (state == "NOT_UPLOADED" and request_state == "NOT_REQUESTED") or retryable:
            from app.tiktok_uploader import save_tiktok_metadata
            save_tiktok_metadata(job_id, copy["title"])
            queued = enqueue(job_id, "tiktok", job_id)
            result["uploads"]["tiktok"] = {
                "queued": True,
                "skipped": False,
                "request_state": queued.get("request_state", "QUEUED"),
                "message": "Upload queued.",
            }
        else:
            result["uploads"]["tiktok"] = {
                "queued": False,
                "skipped": True,
                "state": state,
                "request_state": request_state,
                "message": "An upload record or request already exists. It was not retried.",
            }
    if any(item.get("queued") for item in result["uploads"].values()):
        result["message"] = (
            "Approval recorded and the selected uploads were queued. "
            "YouTube is public. If Instagram was selected, the studio checks the Reel and confirms it after the upload."
        )
        if result["uploads"].get("tiktok", {}).get("queued"):
            result["message"] += " TikTok is queued with this category’s hashtags."
        elif result["uploads"].get("tiktok", {}).get("message") == "TikTok account is not connected":
            result["message"] += " TikTok was not uploaded because the account is not connected."
    elif result["uploads"].get("tiktok", {}).get("message") == "TikTok account is not connected":
        result["message"] = "TikTok account is not connected. Nothing was uploaded."
    else:
        result["message"] = "Nothing new was uploaded. Existing platform records were left unchanged."
    return result
