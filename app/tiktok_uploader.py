"""Upload one approved video to the connected personal TikTok account.

A public post is used when TikTok offers one. Until the production app is
approved, TikTok only allows a private post. Nothing is sent unless
Approve & Publish queued it.
"""

import json
import os
import time
from pathlib import Path

import requests

from app.category_hashtags import category_hashtags, tiktok_caption
from app.publishing_metadata import file_hash
from app.publishing_workflow import JOBS, PUBLISHER, RECORDS, read_json

API = "https://open.tiktokapis.com/v2/post/publish"
TOKEN_FILE = PUBLISHER / "credentials" / "tiktok_token.json"
CLIENT_FILE = PUBLISHER / "credentials" / "tiktok_oauth_client.json"
PRIVACY_ORDER = (
    "PUBLIC_TO_EVERYONE",
    "FOLLOWER_OF_CREATOR",
    "MUTUAL_FOLLOW_FRIENDS",
    "SELF_ONLY",
)


def upload_plan(size):
    """Return chunk size and chunk count for a TikTok file upload."""
    if not isinstance(size, int) or size <= 0:
        raise ValueError("The video file is empty")
    if size < 5 * 1024 * 1024 or size <= 64 * 1024 * 1024:
        return size, 1
    chunk = 10 * 1024 * 1024
    count = size // chunk
    if count < 1 or count > 1000:
        raise ValueError("The video is too large for a TikTok upload")
    return chunk, count


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
    os.replace(tmp, path)


def save_tiktok_metadata(job_id, title):
    """Store the TikTok caption for this video. YouTube and Instagram files stay untouched."""
    folder = JOBS / job_id
    job = read_json(folder / "job.json")
    export = folder / "exports" / "shared_publish_ready.mp4"
    if not export.is_file() or export.stat().st_size <= 0:
        raise ValueError("The publish video is not ready")
    caption = tiktok_caption(title, job.get("category"))
    data = {
        "platform": "tiktok",
        "video_path": str(export.resolve()),
        "video_sha256": file_hash(export),
        "caption": caption,
        "hashtags": list(category_hashtags(job.get("category"))),
        "reviewed_by_admin": True,
        "published": False,
    }
    _write_json(folder / "tiktok_publish_metadata.json", data)
    return data


def _safe_text(value):
    text = " ".join(str(value or "").split())
    lowered = text.lower()
    if any(word in lowered for word in ("token", "bearer", "secret", "authorization", "access_token")):
        return "TikTok rejected the request"
    return text[:180]


def _tiktok_error(payload, fallback):
    if not isinstance(payload, dict):
        return fallback
    err = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    code = str(err.get("code") or "")
    if code and code != "ok":
        detail = _safe_text(err.get("message"))
        return _safe_text((code + " " + detail).strip()) or fallback
    return ""


def _load_token():
    if not TOKEN_FILE.is_file() or TOKEN_FILE.stat().st_mode & 0o077:
        raise ValueError("TikTok account is not connected")
    data = read_json(TOKEN_FILE)
    from app.tiktok_oauth import refreshed_token
    data = refreshed_token(data)
    token = str(data.get("access_token") or "").strip()
    if not token:
        raise ValueError("TikTok account is not connected")
    return data


def _headers(token):
    return {
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json; charset=UTF-8",
    }


def _post(path, token, body=None):
    response = requests.post(
        API + path,
        headers=_headers(token),
        json={} if body is None else body,
        timeout=60,
    )
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    problem = _tiktok_error(payload, "")
    if response.status_code >= 400 or problem:
        raise RuntimeError(problem or f"TikTok HTTP {response.status_code}")
    return payload.get("data") if isinstance(payload.get("data"), dict) else {}


def _choose_privacy(options):
    allowed = {str(item) for item in options or []}
    if "PUBLIC_TO_EVERYONE" in allowed:
        return "PUBLIC_TO_EVERYONE"
    if "SELF_ONLY" in allowed:
        return "SELF_ONLY"
    for level in PRIVACY_ORDER:
        if level in allowed:
            return level
    raise RuntimeError("TikTok did not offer a privacy setting for this account")


def _chunk_ranges(size, chunk, count):
    if count == 1:
        return [(0, size - 1)]
    ranges = []
    for index in range(count):
        start = index * chunk
        end = size - 1 if index == count - 1 else start + chunk - 1
        ranges.append((start, end))
    return ranges


def _send_chunks(upload_url, video, size, chunk, count, on_accepted=None):
    with video.open("rb") as handle:
        for start, end in _chunk_ranges(size, chunk, count):
            handle.seek(start)
            payload = handle.read(end - start + 1)
            response = requests.put(
                upload_url,
                data=payload,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Length": str(len(payload)),
                    "Content-Range": f"bytes {start}-{end}/{size}",
                },
                timeout=180,
            )
            if response.status_code not in {201, 206}:
                raise RuntimeError(f"TikTok upload HTTP {response.status_code}")
            if on_accepted is not None:
                on_accepted()
                on_accepted = None
    return True


def _post_id(data):
    raw = data.get("publicaly_available_post_id") or data.get("publicly_available_post_id") or []
    if isinstance(raw, str):
        raw = [raw]
    for item in raw:
        text = str(item or "").strip()
        if text.isdecimal():
            return text
    return ""


def publish(job_id):
    """Send the approved export to TikTok and record the result. Does not retry by itself."""
    folder = JOBS / job_id
    meta = read_json(folder / "tiktok_publish_metadata.json")
    video = folder / "exports" / "shared_publish_ready.mp4"
    if (
        meta.get("platform") != "tiktok"
        or meta.get("reviewed_by_admin") is not True
        or not isinstance(meta.get("caption"), str)
        or not (1 <= len(meta["caption"]) <= 2200)
        or "DRAFT:" in meta["caption"].upper()
        or not video.is_file()
        or file_hash(video) != meta.get("video_sha256")
        or Path(meta.get("video_path", "")).resolve() != video.resolve()
    ):
        raise ValueError("TikTok metadata does not match this video")
    token_data = _load_token()
    token = str(token_data.get("access_token") or "").strip()
    records = RECORDS / "tiktok"
    records.mkdir(parents=True, exist_ok=True)
    try:
        records.chmod(0o700)
    except OSError:
        pass
    record_path = records / f"{job_id}.json"
    if record_path.exists():
        raise FileExistsError("A TikTok upload record already exists")
    record = {
        "job_id": job_id,
        "platform": "tiktok",
        "state": "STARTED",
        "published": False,
        "upload_started": False,
    }
    _write_json(record_path, record)
    try:
        creator = _post("/creator_info/query/", token)
        privacy = _choose_privacy(creator.get("privacy_level_options"))
        username = str(creator.get("creator_username") or "").strip()
        record.update(privacy_requested=privacy, tiktok_username=username)
        _write_json(record_path, record)
        size = video.stat().st_size
        chunk, count = upload_plan(size)
        init = _post("/video/init/", token, {
            "post_info": {
                "title": meta["caption"],
                "privacy_level": privacy,
                "disable_duet": creator.get("duet_disabled") is True,
                "disable_stitch": creator.get("stitch_disabled") is True,
                "disable_comment": creator.get("comment_disabled") is True,
                "video_cover_timestamp_ms": 1000,
                "brand_content_toggle": False,
                "brand_organic_toggle": False,
                "is_aigc": True,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": size,
                "chunk_size": chunk,
                "total_chunk_count": count,
            },
        })
        publish_id = str(init.get("publish_id") or "").strip()
        upload_url = str(init.get("upload_url") or "").strip()
        if not publish_id or not upload_url.startswith("https://"):
            raise RuntimeError("TikTok did not accept the upload")
        record["publish_id"] = publish_id
        _write_json(record_path, record)

        def mark_started():
            record["upload_started"] = True
            _write_json(record_path, record)

        _send_chunks(upload_url, video, size, chunk, count, mark_started)
        record["upload_started"] = True
        record["state"] = "UPLOADED_PROCESSING"
        _write_json(record_path, record)
        post_id = ""
        status = ""
        for _ in range(24):
            time.sleep(5)
            status_data = _post("/status/fetch/", token, {"publish_id": publish_id})
            status = str(status_data.get("status") or "")
            post_id = _post_id(status_data)
            if status in {"PUBLISH_COMPLETE", "FAILED"}:
                break
        if status == "FAILED" or not post_id and status != "PUBLISH_COMPLETE":
            if status == "FAILED":
                record.update(state="FAILED", upload_started=False, error="TikTok rejected the upload. Check the account, then it can be sent again.")
                _write_json(record_path, record)
                raise RuntimeError(record["error"])
            record.update(state="UPLOADED_PROCESSING", error="TikTok is still processing the video.")
            _write_json(record_path, record)
            return record
        final = "UPLOADED_PRIVATE" if privacy == "SELF_ONLY" else "UPLOADED_PUBLIC"
        record.update(
            state=final,
            published=True,
            tiktok_post_id=post_id,
            tiktok_username=username,
            error="",
        )
        _write_json(record_path, record)
        return record
    except Exception as exc:
        if record.get("state") == "STARTED":
            record.update(state="FAILED", error=_safe_text(exc) or "TikTok upload failed")
            _write_json(record_path, record)
        raise
