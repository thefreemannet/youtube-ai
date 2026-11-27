"""Stage one approved Instagram Reel. NEVER publishes."""

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests

from app.review_gate import review_report

JOB = "20261110-225615-919b89"
ROOT = Path("/opt/j3g-youtube-ai")
FOLDER = ROOT / "data/jobs" / JOB

META = FOLDER / "instagram_publish_metadata.json"
VIDEO = FOLDER / "exports/shared_publish_ready.mp4"
TOKEN = ROOT / "data/publisher/credentials/instagram_access_token.txt"
RECORDS = ROOT / "data/publisher/upload_records/instagram"
RECORD = RECORDS / f"{JOB}.json"
API = "https://graph.facebook.com/v26.0"


def sha256(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def save_record(data):
    temp = RECORD.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    temp.chmod(0o600)
    os.replace(temp, RECORD)


def reel_upload_can_retry(message, attempt, limit=6):
    """Meta sometimes rejects a valid Reel upload and accepts the next session."""
    text = str(message or "")
    return attempt + 1 < limit and "Request processing failed" in text


def checked_response(response):
    try:
        data = response.json()
    except ValueError:
        raise RuntimeError(
            f"Meta returned non-JSON response: HTTP {response.status_code}"
        )

    if not response.ok:
        error = data.get("error", {}) if isinstance(data, dict) else {}
        debug = data.get("debug_info", {}) if isinstance(data, dict) else {}
        detail = " ".join(str(error.get("message") or debug.get("message") or "").split())
        if any(word in detail.lower() for word in ("token", "bearer", "oauth", "access_token")):
            detail = ""
        extra = f" {detail[:180]}" if detail else ""
        raise RuntimeError(
            f"Meta API error: HTTP {response.status_code}, "
            f"code={error.get('code')}, "
            f"subcode={error.get('error_subcode')}.{extra}"
        )

    if not isinstance(data, dict):
        raise RuntimeError("Unexpected Meta API response")

    return data


def main():
    print("=== J3G INSTAGRAM REEL STAGING ===", flush=True)

    if RECORD.exists():
        raise RuntimeError(
            "Previous staging attempt exists. "
            "Manual reconciliation required."
        )

    review = review_report(JOB)
    if not review["approval_current"]:
        raise RuntimeError("Administrator video approval invalid")

    metadata = json.loads(META.read_text(encoding="utf-8"))

    if metadata.get("reviewed_by_admin") is not True:
        raise RuntimeError("Instagram metadata not approved")

    if metadata.get("username") != "thefreemannet":
        raise RuntimeError("Unexpected Instagram account")

    if metadata.get("media_type") != "REELS":
        raise RuntimeError("Unexpected media type")

    if metadata.get("published") is not False:
        raise RuntimeError("Publishing state is not safe")

    if Path(metadata["video_path"]).resolve() != VIDEO.resolve():
        raise RuntimeError("Unexpected video path")

    if sha256(VIDEO) != metadata["video_sha256"]:
        raise RuntimeError("Video integrity verification failed")

    if not 1 <= len(metadata["caption"]) <= 2200:
        raise RuntimeError("Invalid Instagram caption")

    account_id = str(metadata["account_id"])
    if not account_id.isdecimal():
        raise RuntimeError("Invalid Instagram account ID")

    token = TOKEN.read_text(encoding="utf-8").strip()

    RECORDS.mkdir(parents=True, exist_ok=True)
    RECORDS.chmod(0o700)

    state = {
        "job_id": JOB,
        "platform": "instagram",
        "state": "STARTED",
        "account": "thefreemannet",
        "video_sha256": metadata["video_sha256"],
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "published": False
    }

    fd = os.open(
        str(RECORD),
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600
    )

    with os.fdopen(fd, "w") as f:
        json.dump(state, f, indent=2)

    session = requests.Session()
    headers = {"Authorization": f"Bearer {token}"}

    try:
        print("CREATING INSTAGRAM MEDIA CONTAINER...", flush=True)

        response = session.post(
            f"{API}/{account_id}/media",
            headers=headers,
            data={
                "media_type": "REELS",
                "upload_type": "resumable",
                "caption": metadata["caption"],
                "share_to_feed": "false"
            },
            timeout=30
        )

        result = checked_response(response)
        container_id = str(result.get("id", ""))
        upload_uri = result.get("uri", "")

        if not container_id.isdecimal():
            raise RuntimeError("Missing valid container ID")

        state["container_id"] = container_id
        state["state"] = "CONTAINER_CREATED"
        save_record(state)

        target = urlsplit(upload_uri)

        if (
            target.scheme != "https"
            or target.hostname != "rupload.facebook.com"
            or target.username
            or target.password
            or target.port not in (None, 443)
        ):
            raise RuntimeError("Unexpected Meta upload destination")

        print("UPLOADING LOCAL MP4 TO META...", flush=True)

        with VIDEO.open("rb") as file:
            response = session.post(
                upload_uri,
                headers={
                    "Authorization": f"OAuth {token}",
                    "offset": "0",
                    "file_size": str(VIDEO.stat().st_size),
                    "Content-Type": "application/octet-stream"
                },
                data=file,
                timeout=(15, 180)
            )

        result = checked_response(response)

        if result.get("success") is not True:
            raise RuntimeError("Meta did not confirm video transfer")

        state["state"] = "UPLOADED_PROCESSING"
        save_record(state)

        response = session.get(
            f"{API}/{container_id}",
            headers=headers,
            params={"fields": "status_code"},
            timeout=20
        )

        result = checked_response(response)
        status = result.get("status_code", "UNKNOWN")

        state["media_status"] = status

        if status == "FINISHED":
            state["state"] = "READY_TO_PUBLISH"
        elif status in ("ERROR", "EXPIRED"):
            state["state"] = "PROCESSING_FAILED"

        save_record(state)

        print("VIDEO TRANSFER: SUCCESS")
        print("CONTAINER ID:", container_id)
        print("PROCESSING STATUS:", status)
        print("INSTAGRAM REEL: NOT PUBLISHED")

    except Exception as exc:
        state["error_type"] = type(exc).__name__
        state["state"] = "RECONCILIATION_REQUIRED"
        save_record(state)
        print("STAGING ERROR:", str(exc))
        print("DO NOT RETRY WITHOUT INSPECTING THE RECORD")
        sys.exit(1)


if __name__ == "__main__":
    main()
