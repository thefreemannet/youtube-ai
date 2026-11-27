"""Restore jobs left behind when the studio process stops.

A finished preview is marked ready and is not rebuilt. A job that was still
running, with no live worker and no preview, is marked failed so Retry can
be used. Approved, published, and reviewed jobs are left untouched.
Nothing here publishes a video.
"""

import json
import os
from pathlib import Path

ACTIVE_STATES = {
    "QUEUED",
    "RESEARCHING",
    "SCRIPTWRITING",
    "QUALITY_REVIEW",
    "RENDERING_PREVIEW",
}
INTERRUPTED = (
    "The worker stopped before a preview was saved. Use Retry. Nothing was published."
)


def classify(status, preview_complete, worker_alive, uploaded):
    if uploaded:
        return "leave"
    if status not in ACTIVE_STATES:
        return "leave"
    if preview_complete:
        return "mark_ready"
    if worker_alive:
        return "leave"
    return "mark_interrupted"


def worker_alive(folder):
    try:
        pid = int((Path(folder) / "worker.pid").read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _uploaded(folder):
    from app.job_worker import upload_records_exist
    return upload_records_exist(folder.name)


def restore_interrupted(jobs_dir):
    """Return one short line per job whose status changed."""
    jobs_dir = Path(jobs_dir)
    if not jobs_dir.is_dir():
        return []
    from app.job_worker import preview_is_complete
    from app.workflow_dashboard import save_stage

    notes = []
    for folder in sorted(path for path in jobs_dir.iterdir() if path.is_dir()):
        path = folder / "job.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        status = str(data.get("status") or "")
        try:
            complete = preview_is_complete(folder)
            uploaded = _uploaded(folder)
        except (OSError, ValueError, RuntimeError):
            continue
        action = classify(status, complete, worker_alive(folder), uploaded)
        if action == "mark_ready":
            save_stage(folder, "PREVIEW_READY", error="")
            notes.append(f"{folder.name} PREVIEW_READY")
        elif action == "mark_interrupted":
            save_stage(folder, "FAILED", error=INTERRUPTED)
            notes.append(f"{folder.name} FAILED interrupted")
    return notes
