import json
import math
import shlex
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path("/opt/j3g-youtube-ai")
JOBS = ROOT / "data" / "jobs"
VOICE_CFG = ROOT / "voice_config.json"

JOB = sorted([p for p in JOBS.iterdir() if p.is_dir() and (p / "job.json").exists()])[-1]
SLIDES_DIR = JOB / "slides"
SLIDES_DIR.mkdir(exist_ok=True)

cfg = json.loads(VOICE_CFG.read_text(encoding="utf-8"))
speaker = cfg["speaker"]
language = cfg["language"]
speed = cfg["speed"]

narration_path = JOB / "narration_reviewed.txt"
if not narration_path.exists():
    narration_path = JOB / "narration.txt"

narration = narration_path.read_text(encoding="utf-8").strip()
narration = " ".join(narration.split())

# ---------- helper functions ----------
def run(cmd, **kwargs):
    return subprocess.run(cmd, check=True, text=True, **kwargs)

def output(cmd, **kwargs):
    return subprocess.check_output(cmd, text=True, **kwargs).strip()

def find_font(size, bold=False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()

def draw_wrapped(draw, text, font, fill, box, line_spacing=10):
    x, y, w, h = box
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = word if not current else current + " " + word
        bbox = draw.textbbox((0,0), test, font=font)
        if bbox[2] - bbox[0] <= w:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)

    # center block vertically in box
    line_heights = []
    for line in lines:
        bb = draw.textbbox((0,0), line, font=font)
        line_heights.append(bb[3] - bb[1])
    total_h = sum(line_heights) + line_spacing * max(0, len(lines)-1)
    cur_y = y + max(0, (h - total_h)//2)

    for i, line in enumerate(lines):
        bb = draw.textbbox((0,0), line, font=font)
        tw = bb[2] - bb[0]
        th = bb[3] - bb[1]
        draw.text((x + (w - tw)//2, cur_y), line, font=font, fill=fill)
        cur_y += th + line_spacing

def canvas():
    img = Image.new("RGB", (720, 1280), "#0f172a")
    draw = ImageDraw.Draw(img)
    # header and footer bars
    draw.rounded_rectangle((30, 30, 690, 120), radius=24, fill="#0b5cab")
    draw.rounded_rectangle((30, 1140, 690, 1240), radius=24, fill="#111827")
    return img, draw

title_font = find_font(44, bold=True)
sub_font = find_font(28, bold=False)
body_font = find_font(30, bold=False)
big_font = find_font(72, bold=True)

def add_brand(draw):
    draw.text((60, 55), "J3G TECH EXPLAINED", font=title_font, fill="white")
    draw.text((60, 1172), "Automated Multi-Agent YouTube Demo", font=sub_font, fill="#cbd5e1")

def slide_title(draw, text):
    draw.rounded_rectangle((50, 150, 670, 250), radius=22, fill="#1e293b", outline="#38bdf8", width=3)
    draw_wrapped(draw, text, title_font, "white", (70, 165, 580, 70))

# ---------- create slides ----------
slides = []

# Slide 1: intro
img, draw = canvas()
add_brand(draw)
slide_title(draw, "What is BACnet?")
draw.rounded_rectangle((70, 320, 650, 960), radius=28, fill="#1e293b", outline="#60a5fa", width=3)
draw.ellipse((270, 390, 450, 570), fill="#0b5cab", outline="#7dd3fc", width=4)
draw.text((313, 438), "B", font=big_font, fill="white")
draw.text((343, 438), "A", font=big_font, fill="white")
draw.text((375, 438), "C", font=big_font, fill="white")
draw.text((408, 438), "net", font=find_font(46, bold=True), fill="#bfdbfe")
intro_text = (
    "BACnet stands for Building Automation and Control Networks. "
    "It is an open communication standard used so building systems "
    "can exchange information."
)
draw_wrapped(draw, intro_text, body_font, "#e5e7eb", (110, 620, 500, 250), line_spacing=12)
p = SLIDES_DIR / "slide_1_intro.png"
img.save(p)
slides.append(p)

# Slide 2: devices talking
img, draw = canvas()
add_brand(draw)
slide_title(draw, "Different HVAC devices can communicate")
# device boxes
boxes = [
    ((90, 350, 280, 500), "Thermostat"),
    ((440, 350, 630, 500), "Air Handler"),
    ((90, 670, 280, 820), "VAV Box"),
    ((440, 670, 630, 820), "Chiller"),
]
for rect, label in boxes:
    draw.rounded_rectangle(rect, radius=24, fill="#1d4ed8", outline="#93c5fd", width=3)
    bb = draw.textbbox((0,0), label, font=body_font)
    draw.text((rect[0] + ((rect[2]-rect[0])-(bb[2]-bb[0]))//2, rect[1]+55), label, font=body_font, fill="white")
# controller hub
draw.rounded_rectangle((255, 510, 465, 640), radius=28, fill="#0f766e", outline="#99f6e4", width=3)
draw_wrapped(draw, "BACnet Network", body_font, "white", (275, 535, 170, 60))
# connection lines
for pt in [(185,500),(535,500),(185,670),(535,670)]:
    draw.line((360,575, pt[0], pt[1]), fill="#67e8f9", width=6)
draw_wrapped(draw,
    "BACnet improves interoperability by allowing compatible devices to share data over a common protocol.",
    body_font, "#e5e7eb", (80, 900, 560, 150), line_spacing=12)
p = SLIDES_DIR / "slide_2_devices.png"
img.save(p)
slides.append(p)

# Slide 3: objects, properties, services
img, draw = canvas()
add_brand(draw)
slide_title(draw, "Objects, properties, and services")
for i, (x, y, title, text) in enumerate([
    (70, 340, "Objects", "Examples: Analog Input, Binary Output, Schedule"),
    (70, 570, "Properties", "Examples: present-value, status, description"),
    (70, 800, "Services", "Examples: read-property, write-property, alarm reporting"),
]):
    draw.rounded_rectangle((x, y, 650, y+160), radius=24, fill="#1e293b", outline="#38bdf8", width=3)
    draw.text((95, y+18), title, font=find_font(34, bold=True), fill="#7dd3fc")
    draw_wrapped(draw, text, body_font, "#e5e7eb", (100, y+60, 500, 75), line_spacing=10)
p = SLIDES_DIR / "slide_3_structure.png"
img.save(p)
slides.append(p)

# Slide 4: limitation
img, draw = canvas()
add_brand(draw)
slide_title(draw, "Important limitation")
draw.rounded_rectangle((80, 330, 640, 930), radius=28, fill="#3f1d1d", outline="#fca5a5", width=4)
draw.text((250, 390), "WARNING", font=find_font(50, bold=True), fill="#fecaca")
warn = (
    "BACnet is not a universal controller programming tool. "
    "It helps devices communicate, but some manufacturers still require "
    "their own software for setup, programming, or advanced features."
)
draw_wrapped(draw, warn, body_font, "#fee2e2", (120, 520, 480, 250), line_spacing=14)
draw.rounded_rectangle((130, 820, 590, 885), radius=18, fill="#7f1d1d")
draw_wrapped(draw, "Always check the device documentation and PICS.", find_font(28, bold=True), "white", (150, 833, 440, 30))
p = SLIDES_DIR / "slide_4_warning.png"
img.save(p)
slides.append(p)

# Slide 5: BACnet/IP vs BACnet/SC
img, draw = canvas()
add_brand(draw)
slide_title(draw, "BACnet/IP vs BACnet/SC")
draw.rounded_rectangle((70, 340, 320, 930), radius=28, fill="#1e293b", outline="#60a5fa", width=3)
draw.rounded_rectangle((400, 340, 650, 930), radius=28, fill="#102a43", outline="#22d3ee", width=3)
draw.text((140, 380), "BACnet/IP", font=find_font(38, bold=True), fill="white")
draw.text((470, 380), "BACnet/SC", font=find_font(38, bold=True), fill="white")
left = "Traditional BACnet/IP traffic is common, but it is not encrypted by default."
right = "BACnet Secure Connect adds TLS-based secure communication for better cybersecurity."
draw_wrapped(draw, left, body_font, "#e5e7eb", (95, 470, 200, 260), line_spacing=12)
draw_wrapped(draw, right, body_font, "#e5e7eb", (425, 470, 200, 260), line_spacing=12)
draw.text((155, 770), "Interoperability", font=find_font(28, bold=True), fill="#93c5fd")
draw.text((482, 770), "Security", font=find_font(28, bold=True), fill="#67e8f9")
p = SLIDES_DIR / "slide_5_security.png"
img.save(p)
slides.append(p)

# ---------- synthesize audio on VM 107 ----------
remote_out = f"/opt/j3gdigital/creator-studio/data/{JOB.name}_xtts.wav"
health = output([
    "ssh", "-o", "BatchMode=yes", "thefreemannet@192.168.120.107",
    "curl -fsS http://172.18.0.9:8000/health"
])
print("XTTS health:", health)

payload = json.dumps({
    "text": narration,
    "language": language,
    "speaker": speaker,
    "speed": speed,
    "output": f"/data/{JOB.name}_xtts.wav"
})

ssh_cmd = (
    "curl --fail-with-body -sS --max-time 600 "
    "-X POST http://172.18.0.9:8000/synthesize "
    "-H 'Content-Type: application/json' "
    f"-d {shlex.quote(payload)}"
)
xtts_resp = output(["ssh", "thefreemannet@192.168.120.107", ssh_cmd])
print("XTTS synthesis response:", xtts_resp)

audio_out = JOB / "narration_xtts.wav"
run([
    "scp",
    f"thefreemannet@192.168.120.107:{remote_out}",
    str(audio_out)
])

# ---------- compute duration ----------
duration = float(output([
    "ffprobe", "-v", "error",
    "-show_entries", "format=duration",
    "-of", "default=noprint_wrappers=1:nokey=1",
    str(audio_out)
]))
print("Audio duration:", duration)

# ---------- build slideshow list ----------
per = duration / len(slides)
concat_txt = JOB / "slides_concat.txt"
with concat_txt.open("w", encoding="utf-8") as f:
    for slide in slides:
        f.write(f"file '{slide}'\n")
        f.write(f"duration {per:.3f}\n")
    # concat demuxer wants last file repeated
    f.write(f"file '{slides[-1]}'\n")

video_out = JOB / "video_xtts.mp4"

vf = (
    "scale=720:1280:force_original_aspect_ratio=decrease,"
    "pad=720:1280:(ow-iw)/2:(oh-ih)/2:color=0x0f172a,"
    "format=yuv420p"
)

run([
    "ffmpeg", "-y",
    "-f", "concat", "-safe", "0", "-i", str(concat_txt),
    "-i", str(audio_out),
    "-vf", vf,
    "-r", "24",
    "-c:v", "libx264",
    "-preset", "medium",
    "-pix_fmt", "yuv420p",
    "-c:a", "aac",
    "-b:a", "160k",
    "-shortest",
    "-movflags", "+faststart",
    str(video_out)
])

report = {
    "job_id": JOB.name,
    "video": str(video_out),
    "audio": str(audio_out),
    "slides_dir": str(SLIDES_DIR),
    "duration_seconds": round(duration, 2),
    "voice_engine": "xtts",
    "speaker": speaker,
    "language": language,
    "speed": speed,
    "status": "LOCAL_PREVIEW_NATURAL_VOICE",
    "published": False
}
(JOB / "production_report_xtts.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

print("\nNATURAL VIDEO PRODUCTION COMPLETED")
print(json.dumps(report, indent=2))
