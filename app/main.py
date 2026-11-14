"""J3G YouTube AI Business: authenticated generation, review and publishing."""
import hmac
import json
import os
import re
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, PlainTextResponse
from pydantic import BaseModel, Field
from app.review_gate import review_report, decide, attribution_text
from app.dashboard_auth import session_user
from app.dashboard_login import COOKIE_NAME
from app.dashboard_page import render_dashboard

app = FastAPI(title="J3G YouTube AI Business")

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
    record_file = ROOT / "data/publisher/upload_records" / platform / f"{job_id}.json"
    request_file = ROOT / "data/publisher/dashboard_requests" / platform / f"{job_id}.json"
    record = read_json(record_file)
    request_data = read_json(request_file)
    upload_state = str(record.get("state", "RECONCILIATION_REQUIRED" if record_file.exists() else "NOT_UPLOADED"))
    request_state = str(request_data.get("state", "RECONCILIATION_REQUIRED" if request_file.exists() else "NOT_REQUESTED"))
    return upload_state, request_state


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
    }


@app.get("/api/health")
def health():
    return {
        "status": "online",
        "application": "J3G YouTube AI Business",
        "version": "0.4.0-selected-review",
        "publishing": "enabled" if read_json(ROOT / "data/publisher/platforms.json").get("publishing_enabled") is True else "disabled",
    }


@app.get("/api/jobs")
def get_jobs():
    results = []
    if not JOBS.exists():
        return results
    for folder in sorted(JOBS.iterdir(), reverse=True):
        if not folder.is_dir() or not JOB_PATTERN.fullmatch(folder.name):
            continue
        data = read_json(folder / "job.json")
        if not data:
            continue
        production = read_json(folder / "production_report_auto.json")
        if not production:
            production = read_json(folder / "production_report.json")
        try:
            day = datetime.strptime(folder.name[:8], "%Y%m%d").strftime("%B %d, %Y")
        except ValueError:
            day = "Unknown date"
        youtube_state, youtube_request = publisher_state(folder.name, "youtube")
        instagram_state, instagram_request = publisher_state(folder.name, "instagram")
        results.append({
            "job_id": folder.name,
            "topic": data.get("topic"),
            "status": data.get("status", "UNKNOWN"),
            "video_ready": (folder / "video.mp4").is_file(),
            "preview_ready": (folder / "video_auto_preview.mp4").is_file(),
            "duration": production.get("video_duration_seconds", production.get("duration_seconds")),
            "published": youtube_state == "UPLOADED_PRIVATE" or instagram_state == "PUBLISHED",
            "error": data.get("error") or "",
            "day": day,
            "youtube_state": youtube_state,
            "youtube_request": youtube_request,
            "instagram_state": instagram_state,
            "instagram_request": instagram_request,
        })
    return results


@app.post("/api/jobs", status_code=202)
def create_job(body: NewJob, request: Request):
    require_login(request)
    topic = " ".join(body.topic.split())
    if not (5 <= len(topic) <= 180):
        raise HTTPException(422, "Topic length must be 5-180 characters")
    with CREATE_LOCK:
        for job in get_jobs():
            if job["status"] in ACTIVE_STATES:
                raise HTTPException(409, "A video job is already running or awaiting a stage transition")
        JOBS.mkdir(parents=True, exist_ok=True)
        job_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        folder = JOBS / job_id
        folder.mkdir(mode=0o750)
        write_json_atomic(folder / "job.json", {
            "job_id": job_id,
            "topic": topic,
            "status": "QUEUED",
            "created_utc": datetime.now(timezone.utc).isoformat(),
        })
        try:
            launch_worker(folder, job_id)
        except Exception as exc:
            data = read_json(folder / "job.json")
            data.update({"status": "FAILED", "error": "Could not launch worker: " + str(exc)[:200]})
            write_json_atomic(folder / "job.json", data)
            raise HTTPException(500, "Could not start job") from exc
        return {"job_id": job_id, "status": "QUEUED", "published": False}


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
        subprocess.Popen(
            [sys.executable, "-m", "app.job_worker", job_id],
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )


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


@app.get("/videos/{job_id}")
def get_video(job_id: str):
    folder = valid_job(job_id)
    video = folder / "video.mp4"
    if not video.is_file():
        raise HTTPException(404, "Video not found")
    return FileResponse(video, media_type="video/mp4")


@app.get("/videos/{job_id}/preview")
def get_preview(job_id: str):
    folder = valid_job(job_id)
    video = folder / "video_auto_preview.mp4"
    if not video.is_file():
        raise HTTPException(404, "Preview not found")
    return FileResponse(video, media_type="video/mp4")


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return HTMLResponse(render_dashboard(get_jobs(), publishing_banner(), platform_flags()))
