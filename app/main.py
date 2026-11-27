"""J3G YouTube AI Business: authenticated generation, review and publishing."""
import hmac
import json
import os
import re
import signal
import shutil
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel, Field
from app.review_gate import review_report, decide, attribution_text
from app.dashboard_auth import account_overview, is_admin, record_video, session_user, set_account_status
from app.workflow_dashboard import script_needs_expansion
from app.dashboard_accounts import render_accounts
from app.dashboard_login import COOKIE_NAME
from app.categories import category_info, require_category
from app.dashboard_page import render_dashboard

app = FastAPI(title="J3G YouTube AI Business")


@app.on_event("startup")
def restore_interrupted_jobs():
    from app.job_recovery import restore_interrupted
    for note in restore_interrupted(Path(os.environ.get("J3G_ROOT", "/opt/j3g-youtube-ai")) / "data" / "jobs"):
        print("RECOVERY:", note, flush=True)

# J3G dashboard authentication
from app.dashboard_login import router as login_router
from app.dashboard_guard import dashboard_guard

app.include_router(login_router)
app.middleware("http")(dashboard_guard)

ROOT = Path(os.environ.get("J3G_ROOT", "/opt/j3g-youtube-ai"))
JOBS = ROOT / "data" / "jobs"
TOKEN_FILE = ROOT / "data" / "dashboard_token"
JOB_PATTERN = re.compile(r"\d{8}-\d{6}-[a-f0-9]{6}")
CREATE_LOCK = threading.Lock()
ACTIVE_STATES = {
    "QUEUED", "RESEARCHING", "SCRIPTWRITING", "QUALITY_REVIEW",
    "RENDERING_PREVIEW",
}


class NewJob(BaseModel):
    topic: str = Field(min_length=5, max_length=180)
    language: str = "en"
    category: str = "hvac"
    script: str = ""


class LanguageBatch(BaseModel):
    language: str = "en"


class ApprovalRequest(BaseModel):
    watched_video: bool = False
    checked_technical_claims: bool = False
    checked_media_licenses: bool = False


class ChangesRequest(BaseModel):
    note: str = Field(min_length=10, max_length=2000)


class PublishingMetadataRequest(BaseModel):
    title: str = Field(default="", max_length=100)
    description: str = Field(default="", max_length=5000)
    caption: str = Field(default="", max_length=2200)
    confirm_technical: bool = False
    confirm_credits: bool = False


class PublishRequest(BaseModel):
    confirmation: str = Field(min_length=1, max_length=64)


class InstagramEnableRequest(BaseModel):
    confirmation: str = Field(min_length=1, max_length=64)


class ApproveAndPublishRequest(BaseModel):
    watched_video: bool = False
    checked_technical_claims: bool = False
    checked_media_licenses: bool = False
    publish_youtube: bool = False
    publish_instagram: bool = False
    publish_tiktok: bool = False
    confirm_publish: bool = False
    title: str = Field(default="", max_length=100)
    description: str = Field(default="", max_length=5000)
    caption: str = Field(default="", max_length=2200)


def read_json(path):
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path, content):
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(content, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temp, path)


def valid_job(job_id):
    if JOB_PATTERN.fullmatch(job_id) is None:
        raise HTTPException(400, "Invalid job ID")
    folder = JOBS / job_id
    if not folder.is_dir():
        raise HTTPException(404, "Job not found")
    return folder


def require_token(value):
    if not TOKEN_FILE.is_file():
        raise HTTPException(503, "Dashboard token not configured on VM 111")
    secret = TOKEN_FILE.read_text(encoding="utf-8").strip()
    if not secret or not hmac.compare_digest(value or "", secret):
        raise HTTPException(401, "Invalid dashboard token")



def require_login(request: Request):
    username = session_user(request.cookies.get(COOKIE_NAME))
    if username is None:
        raise HTTPException(401, "Authentication required")
    return username


def publisher_state(job_id, platform):
    from app.publishing_workflow import upload_retryable
    record_file = ROOT / "data/publisher/upload_records" / platform / f"{job_id}.json"
    request_file = ROOT / "data/publisher/dashboard_requests" / platform / f"{job_id}.json"
    record = read_json(record_file)
    request_data = read_json(request_file)
    upload_state = str(record.get("state", "RECONCILIATION_REQUIRED" if record_file.exists() else "NOT_UPLOADED"))
    request_state = str(request_data.get("state", "RECONCILIATION_REQUIRED" if request_file.exists() else "NOT_REQUESTED"))
    retry = upload_retryable(
        platform, record, request_state, record_file.exists(),
        str(request_data.get("error_type") or record.get("error_type") or ""),
    )
    return upload_state, request_state, retry


def publishing_banner():
    try:
        config = read_json(ROOT / "data/publisher/platforms.json")
        platforms = config.get("platforms", {})
        names = [
            label for key, label in (
                ("youtube", "YouTube"),
                ("instagram", "Instagram"),
                ("facebook", "Facebook"),
                ("tiktok", "TikTok"),
            )
            if platforms.get(key, {}).get("enabled") is True
        ]
        if config.get("publishing_enabled") is True and names:
            return "Application Online — Publishing Enabled (" + ", ".join(names) + ")"
        return "Application Online — Publishing Disabled"
    except (OSError, ValueError, TypeError, AttributeError):
        return "Application Online — Publishing Status Unavailable"


def platform_flags():
    config = read_json(ROOT / "data/publisher/platforms.json")
    enabled = config.get("publishing_enabled") is True
    platforms = config.get("platforms", {}) if isinstance(config.get("platforms"), dict) else {}
    return {
        "youtube": enabled and platforms.get("youtube", {}).get("enabled") is True,
        "instagram": enabled and platforms.get("instagram", {}).get("enabled") is True,
        "tiktok": enabled and platforms.get("tiktok", {}).get("enabled") is True,
    }


@app.get("/api/health")
def health():
    return {
        "status": "online",
        "application": "J3G YouTube AI Business",
        "version": "0.4.0-selected-review",
        "publishing": "enabled" if read_json(ROOT / "data/publisher/platforms.json").get("publishing_enabled") is True else "disabled",
    }


def job_day(folder_name, data):
    review_day = data.get("review_day") if data.get("source") == "automation" else ""
    stamp = None
    if isinstance(review_day, str):
        try:
            stamp = datetime.strptime(review_day, "%Y-%m-%d")
        except ValueError:
            stamp = None
    if stamp is None:
        try:
            stamp = datetime.strptime(folder_name[:8], "%Y%m%d")
        except ValueError:
            return "", "Unknown date"
    return stamp.strftime("%Y-%m-%d"), stamp.strftime("%B %d, %Y")


def get_jobs():
    from app.publishing_workflow import reconcile_stopped_uploads
    try:
        reconcile_stopped_uploads()
    except OSError:
        pass
    results = []
    if not JOBS.exists():
        return results
    for folder in JOBS.iterdir():
        if not folder.is_dir() or not JOB_PATTERN.fullmatch(folder.name):
            continue
        data = read_json(folder / "job.json")
        if not data:
            continue
        production = read_json(folder / "production_report_auto.json")
        if not production:
            production = read_json(folder / "production_report.json")
        sort_day, day = job_day(folder.name, data)
        youtube_state, youtube_request, youtube_retry = publisher_state(folder.name, "youtube")
        youtube_record = read_json(ROOT / "data/publisher/upload_records/youtube" / f"{folder.name}.json")
        youtube_request_data = read_json(ROOT / "data/publisher/dashboard_requests/youtube" / f"{folder.name}.json")
        youtube_reconnect = (
            not youtube_record.get("youtube_video_id")
            and (
                str(youtube_request_data.get("error_type") or "") == "RefreshError"
                or str(youtube_record.get("error_type") or "") == "RefreshError"
            )
        )
        instagram_state, instagram_request, instagram_retry = publisher_state(folder.name, "instagram")
        instagram_record = read_json(ROOT / "data/publisher/upload_records/instagram" / f"{folder.name}.json")
        from app.instagram_reel_check import safe_permalink
        reel_url = safe_permalink(instagram_record.get("reel_permalink"))
        youtube_url = youtube_watch_url(youtube_record.get("youtube_video_id"))
        tiktok_state, tiktok_request, tiktok_retry = publisher_state(folder.name, "tiktok")
        tiktok_record = read_json(ROOT / "data/publisher/upload_records/tiktok" / f"{folder.name}.json")
        from app.category_hashtags import category_hashtags
        tiktok_url = tiktok_watch_url(tiktok_record.get("tiktok_username"), tiktok_record.get("tiktok_post_id"))
        reel_confirmed = instagram_state == "PUBLISHED" and instagram_record.get("reel_confirmed") is True and bool(reel_url)
        reel_note = ""
        if not reel_confirmed:
            raw_note = str(instagram_record.get("error") or "")
            if raw_note and "token" not in raw_note.lower() and "bearer" not in raw_note.lower():
                reel_note = raw_note[:240]
        awaiting = (
            data.get("source") == "automation"
            and not data.get("parked")
            and data.get("status") not in {"APPROVED", "CHANGES_REQUESTED"}
        )
        preview_ready = (folder / "video_auto_preview.mp4").is_file()
        quality = data.get("quality") if isinstance(data.get("quality"), dict) else {}
        quality_note = str(data.get("quality_warning") or quality.get("result") or "")[:1500]
        narration = ""
        narration_file = folder / "narration.txt"
        if not preview_ready and narration_file.is_file():
            narration = narration_file.read_text(encoding="utf-8")[:2500]
        results.append({
            "job_id": folder.name,
            "topic": data.get("topic"),
            "title": job_title(data, folder),
            "language": "es" if str(data.get("language") or "").lower() == "es" else "en",
            "category": category_info(data.get("category"))["id"],
            "category_label": category_info(data.get("category"))["label"],
            "status": data.get("status", "UNKNOWN"),
            "video_ready": (folder / "video.mp4").is_file(),
            "preview_ready": preview_ready,
            "narration": narration,
            "quality_note": quality_note,
            "duration": production.get("video_duration_seconds", production.get("duration_seconds")),
            "published": youtube_state in {"UPLOADED_PRIVATE", "UPLOADED_PUBLIC"} or instagram_state == "PUBLISHED",
            "error": data.get("error") or "",
            "day": day,
            "sort_day": sort_day,
            "awaiting_approval": awaiting,
            "carried_over": awaiting and str(data.get("slate_day") or "") < str(data.get("review_day") or ""),
            "youtube_state": youtube_state,
            "youtube_request": youtube_request,
            "youtube_retry": youtube_retry,
            "youtube_reconnect": youtube_reconnect,
            "youtube_url": youtube_url,
            "tiktok_state": tiktok_state,
            "tiktok_request": tiktok_request,
            "tiktok_retry": tiktok_retry,
            "tiktok_url": tiktok_url,
            "tiktok_hashtags": " ".join(category_hashtags(data.get("category"))),
            "instagram_state": instagram_state,
            "instagram_request": instagram_request,
            "instagram_retry": instagram_retry,
            "instagram_reel_confirmed": reel_confirmed,
            "instagram_reel_url": reel_url if reel_confirmed else "",
            "instagram_note": reel_note,
        })
    results.sort(key=lambda item: (item["sort_day"], item["job_id"]), reverse=True)
    for item in results:
        item.pop("sort_day", None)
    return results


def job_title(data, folder):
    from app.spanish_titles import display_title
    language = "es" if str(data.get("language") or "").lower() == "es" else "en"
    narration = ""
    if language == "es":
        for name in ("narration_reviewed.txt", "narration.txt"):
            path = folder / name
            if path.is_file():
                narration = path.read_text(encoding="utf-8")[:2500]
                break
    return display_title(data.get("topic"), language, narration)


def tiktok_watch_url(username, post_id):
    handle = str(username or "").strip()
    video = str(post_id or "").strip()
    if re.fullmatch(r"[A-Za-z0-9._]{2,24}", handle) and video.isdecimal():
        return "https://www.tiktok.com/@" + handle + "/video/" + video
    return ""


def youtube_watch_url(video_id):
    text = str(video_id or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", text):
        return "https://www.youtube.com/watch?v=" + text
    return ""


def prepare_daily_slate():
    """The studio no longer makes three videos every day. Set J3G_DAILY_SLATE=1 to turn that back on."""
    if os.environ.get("J3G_DAILY_SLATE", "0") != "1":
        return None
    if not JOBS.is_dir():
        return None
    from app.daily_slate import ensure_daily_slate, studio_today
    try:
        return ensure_daily_slate(
            JOBS,
            ROOT / "data" / "automation" / "state.json",
            studio_today(),
            launch_worker,
            CREATE_LOCK,
        )
    except OSError:
        return None


@app.get("/api/jobs")
def list_jobs():
    prepare_daily_slate()
    return get_jobs()


@app.post("/api/automation/generate-language")
def generate_three_in_language(body: LanguageBatch, request: Request):
    username = require_login(request)
    if not JOBS.is_dir():
        raise HTTPException(503, "Video storage is not available")
    choice = str(body.language or "en").strip().lower()
    if choice not in {"en", "es", "both"}:
        raise HTTPException(422, "Language must be English, Spanish, or both")
    languages = ["en", "es"] if choice == "both" else [choice]
    from app.daily_slate import create_three_in_language, studio_today
    try:
        return create_three_in_language(
            JOBS,
            ROOT / "data" / "automation" / "state.json",
            studio_today(),
            launch_worker,
            languages,
            username,
            CREATE_LOCK,
        )
    except OSError as exc:
        raise HTTPException(500, "Could not create the videos") from exc


@app.post("/api/automation/generate")
def generate_three(request: Request):
    require_login(request)
    if not JOBS.is_dir():
        raise HTTPException(503, "Video storage is not available")
    from app.daily_slate import force_daily_slate, studio_today
    try:
        return force_daily_slate(
            JOBS,
            ROOT / "data" / "automation" / "state.json",
            studio_today(),
            launch_worker,
            CREATE_LOCK,
        )
    except OSError as exc:
        raise HTTPException(500, "Could not create the videos") from exc


@app.delete("/api/jobs/{job_id}")
def remove_job(job_id: str, request: Request):
    require_login(request)
    folder = valid_job(job_id)
    from app.job_worker import upload_records_exist
    from app.daily_slate import dismiss_topic, studio_today
    data = read_json(folder / "job.json")
    platform_copy_kept = upload_records_exist(job_id)
    _stop_job_worker(folder)
    shutil.rmtree(folder, onerror=_force_remove)
    if folder.exists():
        raise HTTPException(500, "The video could not be removed from the side list")
    dismiss_topic(
        ROOT / "data" / "automation" / "state.json",
        studio_today(),
        data.get("topic"),
        data.get("language"),
    )
    return {"deleted": job_id, "platform_copy_kept": platform_copy_kept}


def _stop_job_worker(folder):
    pid_path = folder / "worker.pid"
    if not pid_path.is_file():
        return
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return
    if pid <= 1 or pid == os.getpid():
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return


def _force_remove(func, path, _exc):
    try:
        os.chmod(path, 0o700)
        func(path)
    except OSError:
        return


@app.post("/api/jobs", status_code=202)
def create_job(body: NewJob, request: Request):
    username = require_login(request)
    topic = " ".join(body.topic.split())
    if not (5 <= len(topic) <= 180):
        raise HTTPException(422, "Topic length must be 5-180 characters")
    choice = str(body.language or "en").strip().lower()
    if choice not in {"en", "es", "both"}:
        raise HTTPException(422, "Language must be English, Spanish, or both")
    script = " ".join(str(body.script or "").split())
    if script and choice == "both":
        raise HTTPException(422, "A pasted script is one language. Choose English or Spanish.")
    if script and not 40 <= len(script) <= 4000:
        raise HTTPException(422, "Write at least a few sentences, or leave the script empty. Keep it under 4000 characters.")
    languages = ["en", "es"] if choice == "both" else [choice]
    try:
        category = require_category(body.category)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    with CREATE_LOCK:
        for job in get_jobs():
            if job["status"] in ACTIVE_STATES:
                raise HTTPException(409, "A video job is already running or awaiting a stage transition")
        JOBS.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc)
        pair_id = uuid.uuid4().hex if choice == "both" else ""
        created_ids = []
        folders = []
        for index, language in enumerate(languages):
            job_id = stamp.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
            folder = JOBS / job_id
            folder.mkdir(mode=0o750)
            record = {
                "job_id": job_id,
                "topic": topic,
                "language": language,
                "category": category,
                "status": "QUEUED" if index == 0 else "SCHEDULED",
                "created_utc": stamp.isoformat(),
                "created_by": username,
                "source": "manual",
                "slate_order": index,
            }
            if script:
                record["supplied_script"] = script
                if not script_needs_expansion(script):
                    record["quality"] = {
                        "agent": "quality",
                        "status": "completed",
                        "result": "APPROVE_FOR_HUMAN_REVIEW. The operator supplied this script.",
                    }
            if pair_id:
                record["pair_id"] = pair_id
            write_json_atomic(folder / "job.json", record)
            if script and not script_needs_expansion(script):
                (folder / "narration.txt").write_text(script + "\n", encoding="utf-8")
            record_video(username)
            created_ids.append(job_id)
            folders.append(folder)
        try:
            launch_worker(folders[0], created_ids[0])
        except Exception as exc:
            data = read_json(folders[0] / "job.json")
            data.update({"status": "FAILED", "error": "Could not launch worker: " + str(exc)[:200]})
            write_json_atomic(folders[0] / "job.json", data)
            raise HTTPException(500, "Could not start job") from exc
        return {
            "job_id": created_ids[0],
            "job_ids": created_ids,
            "status": "QUEUED",
            "published": False,
        }


@app.post("/api/jobs/with-picture", status_code=202)
async def create_job_with_picture(request: Request):
    """Same manual video as Create a video, explained from the uploaded picture."""
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" not in content_type.lower():
        raise HTTPException(422, "Upload the picture with the video form")
    payload = await request.body()
    if len(payload) > 9 * 1024 * 1024:
        raise HTTPException(422, "Use a JPEG, PNG, or WebP picture under 8 MB")
    from app.picture_subject import form_picture, save_source_picture
    try:
        fields, raw = form_picture(payload, content_type)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    body = NewJob(
        topic=fields.get("topic", ""),
        language=fields.get("language", "en"),
        category=fields.get("category", "hvac"),
        script=fields.get("script", ""),
    )
    import tempfile
    handle, name = tempfile.mkstemp(suffix=".jpg")
    os.close(handle)
    temporary = Path(name)
    try:
        save_source_picture(raw, temporary)
        jpeg = temporary.read_bytes()
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        temporary.unlink(missing_ok=True)
    created = create_job(body, request)
    for job_id in created["job_ids"]:
        target = JOBS / job_id / "source_picture.jpg"
        target.write_bytes(jpeg)
        os.chmod(target, 0o644)
    return created


@app.get("/api/jobs/{job_id}/publishing")
def get_publishing_status(job_id: str, request: Request):
    require_login(request)
    valid_job(job_id)

    from app.publishing_workflow import inspect

    return inspect(job_id)


@app.post("/api/jobs/{job_id}/publishing/prepare")
def prepare_publishing(job_id: str, request: Request):
    require_login(request)
    valid_job(job_id)
    from app.publishing_workflow import prepare
    try:
        return prepare(job_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (ValueError, FileExistsError, RuntimeError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/jobs/{job_id}/publishing/metadata/{platform}")
def save_publishing_metadata(job_id: str, platform: str, body: PublishingMetadataRequest, request: Request):
    require_login(request)
    valid_job(job_id)
    from app.publishing_workflow import save_metadata
    try:
        return save_metadata(job_id, platform, **body.model_dump())
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (ValueError, FileExistsError, RuntimeError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/jobs/{job_id}/publishing/upload/{platform}", status_code=202)
def upload_publishing(job_id: str, platform: str, body: PublishRequest, request: Request):
    require_login(request)
    valid_job(job_id)
    from app.dashboard_publisher import enqueue
    try:
        return enqueue(job_id, platform, body.confirmation)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (ValueError, FileExistsError, RuntimeError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/publishing/instagram/enable")
def enable_instagram(body: InstagramEnableRequest, request: Request):
    require_login(request)
    if body.confirmation != "ENABLE_INSTAGRAM":
        raise HTTPException(422, "Explicit Instagram enable confirmation required")
    from app.publishing_workflow import CONFIG, read_json as pub_read
    config = pub_read(CONFIG)
    platforms = config.get("platforms", {})
    if not isinstance(platforms.get("instagram"), dict):
        raise HTTPException(409, "Instagram configuration missing")
    if config.get("publishing_enabled") is not True:
        raise HTTPException(409, "Global publishing is disabled")
    from app.publishing_workflow import PUBLISHER
    account = pub_read(PUBLISHER / "instagram_account.json")
    if not str(account.get("account_id", "")).isdecimal():
        raise HTTPException(409, "Instagram account configuration missing")
    token = PUBLISHER / "credentials/instagram_access_token.txt"
    if not token.is_file() or (token.stat().st_mode & 0o077):
        raise HTTPException(409, "Instagram token missing or permissions too open")
    if platforms["instagram"].get("enabled") is True:
        return {"instagram_enabled": True, "changed": False}
    platforms["instagram"]["enabled"] = True
    temp = CONFIG.with_name(CONFIG.name + ".tmp")
    fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(config, out, ensure_ascii=False, indent=2)
        os.replace(temp, CONFIG)
    finally:
        temp.unlink(missing_ok=True)
    return {"instagram_enabled": True, "changed": True, "uploads_performed": False}


@app.get("/api/jobs/{job_id}/review")
def get_review(job_id: str):
    valid_job(job_id)
    try:
        result = review_report(job_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return result


@app.get("/api/jobs/{job_id}/attribution.txt", response_class=PlainTextResponse)
def get_attribution(job_id: str):
    valid_job(job_id)
    try:
        result = review_report(job_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return PlainTextResponse(
        attribution_text(result),
        headers={"Content-Disposition": f'attachment; filename="{job_id}-attribution.txt"'},
    )


@app.post("/api/jobs/{job_id}/review/approve")
def approve_review(job_id: str, body: ApprovalRequest,
                   request: Request):
    require_login(request)
    valid_job(job_id)
    try:
        return decide(job_id, "APPROVED", confirmations=body.model_dump())
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/jobs/{job_id}/review/request-changes")
def request_review_changes(job_id: str, body: ChangesRequest,
                           request: Request):
    require_login(request)
    valid_job(job_id)
    try:
        return decide(job_id, "CHANGES_REQUESTED", note=body.note)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/jobs/{job_id}/approve-and-publish")
def approve_and_publish_job(job_id: str, body: ApproveAndPublishRequest, request: Request):
    require_login(request)
    valid_job(job_id)
    from app.approve_and_publish import approve_and_publish
    try:
        return approve_and_publish(job_id, **body.model_dump())
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (ValueError, FileExistsError, RuntimeError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


def launch_worker(folder, job_id):
    with (folder / "worker.log").open("ab") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "app.job_worker", job_id],
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    (folder / "worker.pid").write_text(str(process.pid), encoding="utf-8")


@app.post("/api/jobs/{job_id}/retry", status_code=202)
def retry_job(job_id: str, request: Request):
    require_login(request)
    folder = valid_job(job_id)
    from app.job_worker import upload_records_exist
    if upload_records_exist(job_id):
        raise HTTPException(409, "This job has a publishing record and will not be rerun")
    with CREATE_LOCK:
        job = read_json(folder / "job.json")
        if job.get("status") != "FAILED":
            raise HTTPException(409, "Only a failed production job can be retried")
        for existing in get_jobs():
            if existing["job_id"] != job_id and existing["status"] in ACTIVE_STATES:
                raise HTTPException(409, "Another video job is still running")
        job["status"] = "QUEUED"
        job["error"] = ""
        write_json_atomic(folder / "job.json", job)
        try:
            launch_worker(folder, job_id)
        except Exception as exc:
            job["status"] = "FAILED"
            job["error"] = "Could not launch worker: " + str(exc)[:200]
            write_json_atomic(folder / "job.json", job)
            raise HTTPException(500, "Could not restart job") from exc
    return {"job_id": job_id, "status": "QUEUED", "published": False}


def video_response(video, job_id, download):
    if download:
        return FileResponse(video, media_type="video/mp4", filename=f"{job_id}.mp4")
    return FileResponse(video, media_type="video/mp4")


@app.get("/videos/{job_id}")
def get_video(job_id: str, download: bool = False):
    folder = valid_job(job_id)
    video = folder / "video.mp4"
    if not video.is_file():
        raise HTTPException(404, "Video not found")
    return video_response(video, job_id, download)


@app.get("/videos/{job_id}/preview")
def get_preview(job_id: str, download: bool = False):
    folder = valid_job(job_id)
    video = folder / "video_auto_preview.mp4"
    if not video.is_file():
        raise HTTPException(404, "Preview not found")
    return video_response(video, job_id, download)


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    username = session_user(request.cookies.get("j3g_session"))
    prepare_daily_slate()
    return HTMLResponse(render_dashboard(
        get_jobs(),
        publishing_banner(),
        platform_flags(),
        is_admin=is_admin(username),
    ))


@app.get("/tiktok/connect", response_class=HTMLResponse)
def tiktok_connect_page(request: Request, error: str = ""):
    username = require_login(request)
    if not is_admin(username):
        raise HTTPException(403, "Only the administrator can connect TikTok")
    from app.tiktok_oauth import connect_page
    notices = {
        "denied": "TikTok login was cancelled. You can try again.",
        "failed": "TikTok did not accept the login. Check the Client key and Client secret, then try again.",
        "invalid": "The Client key or Client secret does not look like a TikTok credential.",
    }
    return HTMLResponse(connect_page(notices.get(error, "")))


@app.post("/tiktok/connect")
async def tiktok_connect_submit(request: Request):
    username = require_login(request)
    if not is_admin(username):
        raise HTTPException(403, "Only the administrator can connect TikTok")
    from urllib.parse import parse_qs
    from app.tiktok_oauth import authorize_url
    raw = await request.body()
    if len(raw) > 4000:
        raise HTTPException(400, "That form is too large")
    fields = parse_qs(raw.decode("utf-8", errors="replace"), keep_blank_values=True, max_num_fields=4)
    try:
        target = authorize_url(
            (fields.get("client_key") or [""])[0],
            (fields.get("client_secret") or [""])[0],
        )
    except ValueError as exc:
        code = "invalid" if "credential" in str(exc) else "failed"
        return RedirectResponse("/tiktok/connect?error=" + code, status_code=303)
    return RedirectResponse(target, status_code=303)


@app.get("/tiktok/callback")
def tiktok_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    username = require_login(request)
    if not is_admin(username):
        raise HTTPException(403, "Only the administrator can connect TikTok")
    if error:
        return RedirectResponse("/tiktok/connect?error=denied", status_code=303)
    from app.tiktok_oauth import finish_login
    try:
        finish_login(code, state)
    except ValueError:
        return RedirectResponse("/tiktok/connect?error=failed", status_code=303)
    return RedirectResponse("/tiktok/connect", status_code=303)


@app.get("/accounts", response_class=HTMLResponse)
def accounts_page():
    return HTMLResponse(render_accounts(account_overview()))


@app.post("/accounts/{username}/{action}")
def account_decision(username: str, action: str):
    if action not in {"approve", "reject"}:
        raise HTTPException(404, "Unknown account action")
    try:
        set_account_status(username, "approved" if action == "approve" else "rejected")
    except LookupError as exc:
        raise HTTPException(404, "Account not found") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return RedirectResponse("/accounts", status_code=303)
