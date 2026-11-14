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
    for platform in ("youtube", "instagram"):
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
    """A preview counts only when the file, solid-background report, and media probe agree."""
    report = read_json(folder / "production_report_auto.json")
    if report.get("background_mode") != "solid" or report.get("photographs") != []:
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
    data = json.loads((folder / "job.json").read_text(encoding="utf-8"))
    if data.get("status") in {"APPROVED", "CHANGES_REQUESTED"}:
        raise RuntimeError("Reviewed jobs are not rendered again")
    topic = data["topic"]
    try:
        if preview_is_complete(folder):
            save_stage(folder, "PREVIEW_READY", error="")
            print("VALID PREVIEW ALREADY EXISTS. NOT REBUILT. NOT PUBLISHED.", flush=True)
            return
        if not agent_draft_ready(data, folder):
            asyncio.run(create_video_draft(topic, job_id=job_id))
            data = json.loads((folder / "job.json").read_text(encoding="utf-8"))
            if not agent_draft_ready(data, folder):
                save_stage(
                    folder,
                    "NEEDS_SCRIPT_REVIEW",
                    error="Quality Agent did not clearly recommend approval for human review. Check the script and review.",
                )
                print("STOP: QUALITY REVIEW FLAGGED. NO VIDEO RENDERED.", flush=True)
                return
        else:
            print("RESUMING RENDER FROM EXISTING NARRATION.", flush=True)
        save_stage(folder, "RENDERING_PREVIEW", error="")
        stale = folder / "video_auto_preview.mp4"
        if stale.is_file():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            stale.rename(folder / f"video_auto_preview.invalid-{stamp}.mp4")
        print("[4] Production Engine: solid backgrounds, XTTS, FFmpeg", flush=True)
        subprocess.run(
            [sys.executable, str(ROOT / "app" / "production_engine_v2.py"), "--job", job_id, "--render"],
            cwd=str(ROOT),
            check=True,
            timeout=1200,
        )
        if not preview_is_complete(folder):
            raise RuntimeError("Production finished but the preview failed media validation")
        save_stage(folder, "PREVIEW_READY", error="")
        print("VIDEO PREVIEW READY. NOT PUBLISHED. HUMAN REVIEW REQUIRED.", flush=True)
    except Exception as exc:
        message = str(exc).strip() or exc.__class__.__name__
        save_stage(folder, "FAILED", error=message[-500:])
        print("JOB FAILED:", message, flush=True)
        raise


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m app.job_worker JOB_ID")
    main(sys.argv[1])
