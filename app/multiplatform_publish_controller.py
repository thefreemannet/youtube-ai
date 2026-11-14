"""J3G multi-platform publishing controller.

Status inspection only. No uploads, API calls, or token handling.
"""

import argparse
import json
from pathlib import Path

from app.youtube_publish_gate import publishing_preflight

ROOT = Path("/opt/j3g-youtube-ai")
CONFIG = ROOT / "data/publisher/platforms.json"
JOBS = ROOT / "data/jobs"

PLATFORMS = (
    "youtube",
    "instagram",
    "tiktok",
    "facebook",
)


def inspect_job(job_id):
    gate = publishing_preflight(job_id)

    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    configured = config.get("platforms", {})

    export = JOBS / job_id / "exports/shared_publish_ready.mp4"
    export_exists = export.is_file() and export.stat().st_size > 0

    results = {}

    for platform in PLATFORMS:
        settings = configured.get(platform)

        if not isinstance(settings, dict):
            status = "CONFIGURATION_MISSING"

        elif not gate["ready_for_oauth_upload"]:
            status = "BLOCKED_REVIEW"

        elif not config.get("publishing_enabled", False):
            status = "PUBLISHING_DISABLED"

        elif not settings.get("enabled", False):
            status = "PLATFORM_DISABLED"

        elif not export_exists:
            status = "EXPORT_REQUIRED"

        else:
            # Upload handlers and credentials are not yet implemented.
            status = "UPLOADER_NOT_CONFIGURED"

        results[platform] = {
            "status": status,
            "uploaded": False,
            "remote_video_id": None,
            "remote_url": None,
        }

    return {
        "job_id": job_id,
        "review_approved": gate["ready_for_oauth_upload"],
        "export_available": export_exists,
        "upload_performed": False,
        "platforms": results,
        "blocking_reasons": gate["blocking_reasons"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    args = parser.parse_args()

    result = inspect_job(args.job)
    print(json.dumps(result, indent=2))
    print("\nSTATUS CHECK COMPLETE — NOTHING UPLOADED")
