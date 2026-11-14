"""J3G shared video exporter.

Never uploads videos. Never modifies source previews.
Requires current administrator approval before exporting.
"""

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

from app.review_gate import JOBS
from app.youtube_publish_gate import publishing_preflight


def probe(path):
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries",
            "format=duration,size:"
            "stream=codec_type,codec_name,width,height,"
            "r_frame_rate,sample_rate,channels",
            "-of", "json", str(path)
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=30
    )
    return json.loads(result.stdout)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main(job_id, prepare=False):
    gate = publishing_preflight(job_id)
    folder = JOBS / job_id
    source = folder / "video_auto_preview.mp4"

    print("=== J3G MULTI-PLATFORM EXPORTER ===")
    print("JOB:", job_id)

    if not source.is_file():
        print("STATUS: BLOCKED — NO VIDEO")
        return

    info = probe(source)
    streams = info.get("streams", [])

    video = next(
        (s for s in streams if s.get("codec_type") == "video"),
        {}
    )
    audio = next(
        (s for s in streams if s.get("codec_type") == "audio"),
        {}
    )

    print("VIDEO:", video.get("codec_name"))
    print("RESOLUTION:", video.get("width"), "x", video.get("height"))
    print("FRAME RATE:", video.get("r_frame_rate"))
    print("AUDIO:", audio.get("codec_name"))
    print("SAMPLE RATE:", audio.get("sample_rate"))
    print("DURATION:", info.get("format", {}).get("duration"))
    print("ADMINISTRATOR APPROVAL:", gate["approval_current"])

    problems = list(gate["blocking_reasons"])

    if (
        video.get("codec_name") != "h264"
        or video.get("width") != 720
        or video.get("height") != 1280
        or audio.get("codec_name") != "aac"
    ):
        problems.append("Unexpected media format")

    if problems:
        print("STATUS: BLOCKED")
        for reason in problems:
            print("REASON:", reason)
        print("EXPORT: NOT CREATED")
        return

    print("STATUS: READY FOR LOCAL EXPORT")

    if not prepare:
        print("EXPORT: NOT CREATED — CHECK ONLY")
        return

    export_dir = folder / "exports"
    export_dir.mkdir(mode=0o750, exist_ok=True)

    output = export_dir / "shared_publish_ready.mp4"

    if output.exists():
        raise RuntimeError("Export already exists; refusing to overwrite")

    fd, temporary_name = tempfile.mkstemp(
        prefix=".export_",
        suffix=".mp4",
        dir=export_dir
    )
    os.close(fd)
    temporary = Path(temporary_name)

    try:
        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-y",
                "-hide_banner", "-loglevel", "error",
                "-i", str(source),
                "-map", "0:v:0",
                "-map", "0:a:0",
                "-c:v", "copy",
                "-c:a", "aac",
                "-ar", "48000",
                "-ac", "2",
                "-b:a", "128k",
                "-movflags", "+faststart",
                str(temporary)
            ],
            check=True,
            timeout=300
        )

        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise RuntimeError("Export file missing or empty")

        # Recheck approval after conversion.
        final_gate = publishing_preflight(job_id)

        if not final_gate["ready_for_oauth_upload"]:
            raise RuntimeError("Approval changed during export")

        temporary.rename(output)

        print("EXPORT CREATED:", output)
        print("SHA256:", sha256(output))

    finally:
        temporary.unlink(missing_ok=True)

    print("YOUTUBE UPLOAD: NOT PERFORMED")
    print("INSTAGRAM UPLOAD: NOT PERFORMED")
    print("TIKTOK UPLOAD: NOT PERFORMED")
    print("FACEBOOK UPLOAD: NOT PERFORMED")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    parser.add_argument("--prepare", action="store_true")

    args = parser.parse_args()
    main(args.job, args.prepare)
