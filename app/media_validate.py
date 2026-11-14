"""Validate a finished vertical preview before it can count as complete."""

import json
import subprocess
from pathlib import Path


def validate_preview(path):
    """Require a non-empty 720x1280 file with narration audio and real duration.

    Raises ValueError when the file cannot be published as a finished preview.
    """
    video = Path(path)
    if not video.is_file() or video.stat().st_size < 1000:
        raise ValueError("Preview file is missing or empty")
    proc = subprocess.run(
        [
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_streams", "-show_format", str(video),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or "ffprobe could not read the preview").strip()
        raise ValueError("Media validation failed: " + detail[-300:])
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError("Media validation failed: ffprobe returned unreadable output") from exc
    streams = data.get("streams") or []
    picture = next((item for item in streams if item.get("codec_type") == "video"), None)
    narration = next((item for item in streams if item.get("codec_type") == "audio"), None)
    if picture is None:
        raise ValueError("Preview has no video stream")
    if narration is None:
        raise ValueError("Preview has no narration audio")
    width = int(picture.get("width") or 0)
    height = int(picture.get("height") or 0)
    if (width, height) != (720, 1280):
        raise ValueError(f"Preview must be 720x1280, found {width}x{height}")
    try:
        duration = float((data.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("Preview duration is unreadable") from exc
    if duration <= 1:
        raise ValueError("Preview duration is too short to be a finished video")
    return {
        "width": width,
        "height": height,
        "duration_seconds": round(duration, 2),
        "has_audio": True,
    }
