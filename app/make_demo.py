import json
import subprocess
from pathlib import Path

ROOT = Path("/opt/j3g-youtube-ai")
JOBS = ROOT / "data" / "jobs"

job = sorted(
    p for p in JOBS.iterdir()
    if p.is_dir() and (p / "job.json").exists()
)[-1]

narration = """How do HVAC controllers from different manufacturers
share information? One answer is BACnet, Building Automation
and Control Networks.

BACnet is an open building automation communication standard.
It defines objects and services so compatible systems can
exchange values such as temperature, fan status, schedules,
and alarms.

Technicians can use BACnet diagnostic tools to discover
devices and read supported properties.

But here's an important limitation. BACnet does not
standardize how each controller is programmed.
Manufacturer-specific software may still be required.

Not every device supports the same features, so always
check its PICS document.

BACnet supports IP and MS/TP networking.
And security matters. Traditional BACnet/IP traffic
is not encrypted, while BACnet Secure Connect uses TLS.

In short, BACnet improves interoperability, but successful
integration still requires proper configuration and verification.
"""

narration = " ".join(narration.split())
(job / "narration_reviewed.txt").write_text(narration)

audio = job / "narration.wav"
video = job / "video.mp4"

subprocess.run([
    "espeak-ng",
    "-v", "en-us",
    "-s", "140",
    "-w", str(audio),
    narration
], check=True)

duration = float(subprocess.check_output([
    "ffprobe", "-v", "error",
    "-show_entries", "format=duration",
    "-of", "default=noprint_wrappers=1:nokey=1",
    str(audio)
], text=True).strip())

slides = [
    "WHAT IS BACnet?",
    "A common language\nfor building automation",
    "Objects, properties\nand supported services",
    "BACnet is NOT a universal\ncontroller programming tool",
    "BACnet/IP vs BACnet/SC\nInteroperability and security"
]

filters = [
    "drawtext=text='J3G TECH EXPLAINED':"
    "fontsize=38:fontcolor=cyan:"
    "x=(w-text_w)/2:y=150"
]

for i, slide in enumerate(slides):
    path = job / f"slide_{i}.txt"
    path.write_text(slide)

    start = duration * i / len(slides)
    end = duration * (i + 1) / len(slides)

    filters.append(
        f"drawtext=textfile='{path}':"
        "fontsize=42:"
        "fontcolor=white:"
        "line_spacing=16:"
        "x=(w-text_w)/2:"
        "y=(h-text_h)/2:"
        f"enable='between(t,{start:.2f},{end:.2f})'"
    )

filters.append(
    "drawtext=text='Educational Demo | J3G AI':"
    "fontsize=24:fontcolor=gray:"
    "x=(w-text_w)/2:y=h-140"
)

subprocess.run([
    "ffmpeg", "-y",
    "-f", "lavfi",
    "-i", "color=c=0x101c30:s=720x1280:r=24",
    "-i", str(audio),
    "-vf", ",".join(filters),
    "-c:v", "libx264",
    "-preset", "ultrafast",
    "-pix_fmt", "yuv420p",
    "-c:a", "aac",
    "-b:a", "128k",
    "-shortest",
    "-movflags", "+faststart",
    str(video)
], check=True)

report = {
    "job_id": job.name,
    "video": str(video),
    "duration_seconds": round(duration, 2),
    "status": "LOCAL_PREVIEW",
    "published": False,
    "narration": "human_corrected",
    "audio_engine": "espeak-ng"
}

(job / "production_report.json").write_text(
    json.dumps(report, indent=2)
)

print("\nVIDEO PRODUCTION COMPLETED")
print(json.dumps(report, indent=2))
