"""J3G YouTube uploader. New uploads are public.

Requires human-approved video, reviewed metadata,
explicit upload command and enabled configuration.
No automatic retries.
"""

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from app.review_gate import JOBS
from app.youtube_publish_gate import publishing_preflight

ROOT = Path("/opt/j3g-youtube-ai")
PUBLISHER = ROOT / "data/publisher"
CONFIG = PUBLISHER / "platforms.json"
CREDENTIALS = PUBLISHER / "credentials/youtube_token.json"
SCOPE = "https://www.googleapis.com/auth/youtube.upload"


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()


def check(job_id):
    gate = publishing_preflight(job_id)
    folder = JOBS / job_id
    video = folder / "video_auto_preview.mp4"
    metadata_file = folder / "youtube_publish_metadata.json"

    config = json.loads(CONFIG.read_text())
    youtube = config.get("platforms", {}).get("youtube", {})

    reasons = list(gate["blocking_reasons"])

    if config.get("publishing_enabled") is not True:
        reasons.append("Global publishing is disabled")

    if youtube.get("enabled") is not True:
        reasons.append("YouTube publishing is disabled")

    if not CREDENTIALS.is_file():
        reasons.append("YouTube OAuth token is missing")
    elif (CREDENTIALS.stat().st_mode & 0o777) != 0o600:
        reasons.append("OAuth token permissions are insecure")

    metadata = {}

    if not metadata_file.is_file():
        reasons.append("Reviewed YouTube metadata is missing")
    else:
        try:
            metadata = json.loads(metadata_file.read_text())
        except (ValueError, OSError):
            reasons.append("YouTube metadata is invalid")

    title = metadata.get("title")
    description = metadata.get("description")

    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 100:
        reasons.append("Title must contain 1-100 characters")

    if not isinstance(description, str) or len(description) > 5000:
        reasons.append("Description is missing or too long")

    if metadata.get("reviewed_by_admin") is not True:
        reasons.append("Publishing metadata lacks administrator review")

    if not video.is_file():
        reasons.append("Approved video missing")
    elif metadata.get("approved_video_sha256") != digest(video):
        reasons.append("Metadata does not match approved video")

    records = PUBLISHER / "upload_records/youtube"
    record = records / f"{job_id}.json"

    if record.exists():
        reasons.append(
            "A previous upload attempt exists; "
            "manual reconciliation required"
        )

    return {
        "job_id": job_id,
        "ready": not reasons,
        "privacy": "public",
        "uploaded": False,
        "blocking_reasons": list(dict.fromkeys(reasons))
    }


def upload_private(job_id, confirmation):
    if confirmation != job_id:
        raise ValueError("Explicit job confirmation does not match")

    result = check(job_id)

    if not result["ready"]:
        raise RuntimeError(
            "Upload blocked: " + "; ".join(result["blocking_reasons"])
        )

    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    folder = JOBS / job_id
    video = folder / "video_auto_preview.mp4"
    metadata = json.loads(
        (folder / "youtube_publish_metadata.json").read_text()
    )

    credentials = Credentials.from_authorized_user_file(
        str(CREDENTIALS), scopes=[SCOPE]
    )

    if not credentials.has_scopes([SCOPE]):
        raise RuntimeError("YouTube upload scope missing")

    records = PUBLISHER / "upload_records/youtube"
    records.mkdir(parents=True, exist_ok=True)
    records.chmod(0o700)

    record = records / f"{job_id}.json"

    def write_record(value):
        temporary = record.with_suffix(".tmp")
        fd = os.open(
            str(temporary),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600
        )
        with os.fdopen(fd, "w") as f:
            json.dump(value, f, indent=2)
        os.replace(temporary, record)

    # Claim this job before starting any network upload.
    fd = os.open(
        str(record),
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600
    )
    with os.fdopen(fd, "w") as f:
        json.dump({
            "job_id": job_id,
            "state": "STARTED",
            "privacy": "public",
            "video_sha256": digest(video),
            "started_utc": datetime.now(timezone.utc).isoformat()
        }, f, indent=2)

    started_network = False
    try:
        service = build(
            "youtube", "v3",
            credentials=credentials,
            cache_discovery=False
        )

        # Approval must remain current immediately before upload.
        if not publishing_preflight(job_id)["ready_for_oauth_upload"]:
            raise RuntimeError("Administrator approval is no longer valid")

        if digest(video) != metadata["approved_video_sha256"]:
            raise RuntimeError("Video changed before upload")

        request = service.videos().insert(
            part="snippet,status",
            body={
                "snippet": {
                    "title": metadata["title"].strip(),
                    "description": metadata["description"],
                    "categoryId": "27"
                },
                "status": {
                    "privacyStatus": "public"
                }
            },
            media_body=MediaFileUpload(
                str(video),
                mimetype="video/mp4",
                resumable=True,
                chunksize=1024 * 1024
            )
        )

        response = None
        started_network = True

        while response is None:
            _, response = request.next_chunk(
                num_retries=0
            )

        video_id = response.get("id")

        if not video_id:
            raise RuntimeError("YouTube did not return a video ID")

        write_record({
            "job_id": job_id,
            "state": "UPLOADED_PUBLIC",
            "privacy_requested": "public",
            "youtube_video_id": video_id,
            "video_sha256": metadata["approved_video_sha256"],
            "completed_utc": datetime.now(timezone.utc).isoformat()
        })

        print("YOUTUBE PRIVATE UPLOAD ACCEPTED")
        print("VIDEO ID:", video_id)
        print("VERIFY PRIVACY IN YOUTUBE STUDIO")

    except Exception as exc:
        auth_failed = type(exc).__name__ == "RefreshError" or "invalid_grant" in str(exc).lower()
        failure = {
            "job_id": job_id,
            "state": "RECONCILIATION_REQUIRED",
            "error_type": type(exc).__name__,
            "note": (
                "YouTube did not accept this video. Check it again, then use Approve & Publish."
                if auth_failed else
                "Upload may or may not have reached YouTube. Inspect YouTube Studio before any retry."
            ),
        }
        if started_network and not auth_failed:
            failure["upload_started"] = True
        write_record(failure)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    parser.add_argument("--upload-private", action="store_true")
    parser.add_argument("--confirm-job")

    args = parser.parse_args()

    if args.upload_private:
        upload_private(args.job, args.confirm_job)
    else:
        print(json.dumps(check(args.job), indent=2))
        print("CHECK ONLY — NOTHING UPLOADED")
