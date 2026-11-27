"""Detached job worker for dashboard submissions. NO automatic publishing."""
import asyncio
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.media_validate import validate_preview
from app.workflow_dashboard import create_video_draft, save_stage

ROOT = Path(os.environ.get("J3G_ROOT", "/opt/j3g-youtube-ai"))
JOBS = ROOT / "data" / "jobs"
PUBLISHER = ROOT / "data" / "publisher"


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, ValueError):
        return {}


def upload_records_exist(job_id):
    for platform in ("youtube", "instagram", "tiktok"):
        if (PUBLISHER / "upload_records" / platform / f"{job_id}.json").exists():
            return True
        if (PUBLISHER / "dashboard_requests" / platform / f"{job_id}.json").exists():
            return True
    return False


def agent_draft_ready(data, folder):
    narration = folder / "narration.txt"
    quality = str((data.get("quality") or {}).get("result") or "")
    upper = quality.upper()
    return (
        narration.is_file()
        and narration.stat().st_size > 0
        and "APPROVE_FOR_HUMAN_REVIEW" in upper
        and "REVISE" not in upper
    )


def preview_is_complete(folder):
    """A preview counts only when the file, background report, and media probe agree."""
    report = read_json(folder / "production_report_auto.json")
    photos = report.get("photographs")
    mode = report.get("background_mode")
    if not isinstance(photos, list):
        return False
    if mode == "solid":
        if photos:
            return False
    elif mode == "photo":
        if photos:
            try:
                opacity = float(report.get("background_opacity"))
            except (TypeError, ValueError):
                return False
            if not 0.05 <= opacity <= 0.10:
                return False
    elif mode == "cartoon":
        if photos:
            return False
    else:
        return False
    try:
        validate_preview(folder / "video_auto_preview.mp4")
    except (OSError, ValueError, RuntimeError):
        return False
    return True


def main(job_id):
    if not re.fullmatch(r"\d{8}-\d{6}-[a-f0-9]{6}", job_id):
        raise ValueError("Invalid job ID")
    if upload_records_exist(job_id):
        raise RuntimeError("This job already has a publishing record and will not be rendered again")
    folder = JOBS / job_id
    from app.limits import ensure_free_space
    free = ensure_free_space(folder if folder.exists() else ROOT)
    print(f"DISK FREE: {free} bytes", flush=True)
    data = json.loads((folder / "job.json").read_text(encoding="utf-8"))
    if data.get("status") in {"APPROVED", "CHANGES_REQUESTED"}:
        raise RuntimeError("Reviewed jobs are not rendered again")
    topic = data["topic"]
    try:
        if preview_is_complete(folder):
            save_stage(folder, "PREVIEW_READY", error="")
            print("VALID PREVIEW ALREADY EXISTS. NOT REBUILT. NOT PUBLISHED.", flush=True)
            return
        warning = ""
        narration = folder / "narration.txt"
        if not narration.is_file() or narration.stat().st_size == 0:
            asyncio.run(create_video_draft(topic, job_id=job_id))
            data = json.loads((folder / "job.json").read_text(encoding="utf-8"))
            narration = folder / "narration.txt"
            if not narration.is_file() or narration.stat().st_size == 0:
                save_stage(
                    folder,
                    "NEEDS_SCRIPT_REVIEW",
                    error="Quality Agent did not clearly recommend approval for human review. Check the script and review.",
                )
                print("STOP: NO NARRATION. NO VIDEO RENDERED.", flush=True)
                return
        if not agent_draft_ready(data, folder):
            quality = data.get("quality") if isinstance(data.get("quality"), dict) else {}
            warning = str((quality or {}).get("result") or "Quality review asked for a revision.")[:1500]
            print("QUALITY WARNED. RENDERING A PREVIEW SO IT CAN BE REVIEWED.", flush=True)
        else:
            print("RESUMING RENDER FROM EXISTING NARRATION.", flush=True)
        save_stage(folder, "RENDERING_PREVIEW", error="", quality_warning=warning)
        stale = folder / "video_auto_preview.mp4"
        if stale.is_file():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            stale.rename(folder / f"video_auto_preview.invalid-{stamp}.mp4")
        print("[4] Production Engine: cached backgrounds or solid fallback, XTTS, FFmpeg", flush=True)
        completed = subprocess.run(
            [sys.executable, str(ROOT / "app" / "production_engine_v2.py"), "--job", job_id, "--render"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=3600,
        )
        if completed.stdout:
            print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n", flush=True)
        if completed.stderr:
            print(completed.stderr, end="" if completed.stderr.endswith("\n") else "\n", flush=True)
        if completed.returncode:
            detail = completed.stdout + "\n" + completed.stderr
            reason = ""
            for line in detail.splitlines():
                if "PRODUCTION ERROR" in line or "Text does not fit" in line:
                    reason = line.strip()
            raise RuntimeError(reason[-500:] or f"Production failed ({completed.returncode})")
        if not preview_is_complete(folder):
            raise RuntimeError("Production finished but the preview failed media validation")
        save_stage(folder, "PREVIEW_READY", error="")
        print("VIDEO PREVIEW READY. NOT PUBLISHED. HUMAN REVIEW REQUIRED.", flush=True)
    except Exception as exc:
        message = str(exc).strip() or exc.__class__.__name__
        save_stage(folder, "FAILED", error=message[-500:])
        print("JOB FAILED:", message, flush=True)
        raise
    finally:
        try:
            from app.daily_slate import start_next_scheduled
            from app.main import launch_worker
            started = start_next_scheduled(JOBS, launch_worker, after_job_id=job_id)
            if started:
                print("NEXT VIDEO:", started, flush=True)
        except Exception as exc:
            print("NEXT VIDEO:", exc, flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m app.job_worker JOB_ID")
    main(sys.argv[1])
