"""Cartoon lesson frames for YouTube Shorts, Instagram Reels, and TikTok.

The picture stays the flat cartoon from the reference: thick outlines and one
repeating character. The frame is the same 720 by 1280 vertical size the studio
already used, so a downloaded file can be posted to all three apps. Captions are
drawn locally, so the model cannot misspell the words.

Nothing here publishes a video. Copy this file to the studio later:

    /opt/j3g-youtube-ai/app/cartoon_scenes.py

Pictures are drawn by OpenRouter. A local picture service is used only when
J3G_CARTOON_URL points at one. The OpenRouter key is never printed.
"""

import argparse
import base64
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH = 720
HEIGHT = 1280
# One Gemini picture costs about 4 cents. Each scene gets its own picture.
PAID_MODEL = os.environ.get("J3G_CARTOON_MODEL", "google/gemini-2.5-flash-image")
DEFAULT_PICTURE_URL = "https://openrouter.ai/api/v1/images"


def picture_url():
    return os.environ.get("J3G_CARTOON_URL", DEFAULT_PICTURE_URL).strip()


def uses_paid_pictures():
    return "openrouter.ai" in picture_url()

CHARACTER = (
    "the same cartoon HVAC technician in every scene: a young person with messy orange hair, "
    "a blue work shirt with the sleeves rolled, dark gray work pants, brown work boots, "
    "and a tool belt with a screwdriver and a wrench. No lab coat, no white coat, no scrubs, "
    "no stethoscope, no glasses, no scientist, and no doctor. "
    "Large expressive eyes, thick black outlines, flat solid colors"
)
STYLE = (
    "Flat 2D educational cartoon, thick black ink outlines, solid colors, no gradients, "
    "no photorealism, no 3D, simple background, one clear action. "
    "Do not draw any words, letters, numbers, captions, subtitles, logos, or watermarks. "
    "Vertical 9:16 phone video. Place the character and the action in the upper two thirds. "
    "Keep the bottom area visually simple so a caption can sit there. "
    + CHARACTER
)


def project_root():
    return Path(__file__).resolve().parents[1]


def load_key():
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if key:
        return key
    path = project_root() / "openrouter.key"
    if path.is_file():
        key = path.read_text(encoding="utf-8").strip()
        if key:
            return key
    raise SystemExit(
        "OpenRouter key not found. Put one line in "
        + str(project_root() / "openrouter.key")
        + " or set OPENROUTER_API_KEY. The side browser cannot sign in to Google."
    )


def font_path():
    candidates = [
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for path in candidates:
        if Path(path).is_file():
            return path
    raise FileNotFoundError("No caption font found")


def sentences(text):
    parts = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
    return [part.strip() for part in parts if part.strip()]


def group_scenes(text, count=5):
    units = sentences(text)
    if not units:
        raise ValueError("Narration is empty")
    count = max(1, min(count, len(units)))
    groups = []
    index = 0
    for slot in range(count):
        remaining_slots = count - slot
        end = len(units) - (remaining_slots - 1)
        words_left = sum(len(part.split()) for part in units[index:])
        target = words_left / remaining_slots
        best = index + 1
        best_delta = float("inf")
        for stop in range(index + 1, end + 1):
            words = sum(len(part.split()) for part in units[index:stop])
            delta = abs(words - target)
            if delta < best_delta:
                best, best_delta = stop, delta
        groups.append(" ".join(units[index:best]))
        index = best
    return groups


def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def _picture_busy(code, detail):
    text = str(detail or "").lower()
    if code == 429:
        return True
    return code == 402 and ("in_flight" in text or "in-flight" in text)


def generate_image(prompt, key, reference_png=None):
    """Ask for one picture. A busy picture service is asked again after a wait."""
    for attempt in range(6):
        try:
            return _request_image(prompt, key, reference_png)
        except RuntimeError as exc:
            message = str(exc)
            busy = "failed (429)" in message or ("failed (402)" in message and _picture_busy(402, message))
            if not busy or attempt == 5:
                raise
            wait = 20 * (attempt + 1)
            print(f"PICTURE SERVICE BUSY. WAITING {wait} SECONDS.", flush=True)
            time.sleep(wait)


def picture_prompt(prompt, paid=None):
    """Keep the spoken script out of a local picture. The subtitle track carries those words."""
    if paid is None:
        paid = uses_paid_pictures()
    if paid:
        return prompt
    marker = "Scene action, shown literally with simple props:"
    head = prompt.split(marker, 1)[0].rstrip()
    return (
        "Exactly two arms and exactly two hands. Both arms hang straight down. "
        "One head. Do not raise a hand. Do not add a third arm, an extra hand, or extra fingers. "
        "Draw no letters, no words, no numbers, and no captions in any language. "
        "The area under the character stays empty. "
        + head
    )


def _request_image(prompt, key, reference_png=None):
    if uses_paid_pictures():
        payload = {
            "model": PAID_MODEL,
            "prompt": prompt,
            "aspect_ratio": "9:16",
            "resolution": "1K",
            "output_format": "png",
            "n": 1,
        }
        if reference_png is not None:
            encoded = base64.b64encode(reference_png).decode("ascii")
            payload["input_references"] = [{
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64," + encoded},
            }]
        headers = {
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
        }
    else:
        payload = {
            "prompt": picture_prompt(prompt, paid=False),
            "width": WIDTH,
            "height": HEIGHT,
        }
        if reference_png is not None:
            payload["reference_png_base64"] = base64.b64encode(reference_png).decode("ascii")
        headers = {"Content-Type": "application/json"}
    request = urllib.request.Request(
        picture_url(),
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        if reference_png is not None and exc.code in (400, 422):
            return generate_image(prompt, key, reference_png=None)
        label = "Paid picture request" if uses_paid_pictures() else "Local picture request"
        raise RuntimeError(f"{label} failed ({exc.code}): {detail}") from exc
    images = result.get("data") or []
    if not images or not images[0].get("b64_json"):
        raise RuntimeError("The picture service returned no image")
    return base64.b64decode(images[0]["b64_json"])


def scene_prompt(caption):
    return (
        STYLE
        + " The person is an HVAC field technician in work clothes, never a doctor or a scientist."
        + " Scene action, shown literally with simple props: "
        + caption
    )


def wrap_caption(draw, text, font, width):
    lines = []
    current = ""
    for word in text.split():
        trial = (current + " " + word).strip()
        if draw.textlength(trial, font=font) <= width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def draw_caption(image, text):
    frame = image.convert("RGB").resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(frame)
    font = None
    lines = []
    line_height = 44
    for size in (34, 30, 26, 22):
        font = ImageFont.truetype(font_path(), size)
        lines = wrap_caption(draw, text, font, WIDTH - 72)
        line_height = size + 12
        if len(lines) <= 4:
            break
    block = line_height * len(lines)
    top = HEIGHT - 48 - block
    for index, line in enumerate(lines):
        line_width = draw.textlength(line, font=font)
        x = (WIDTH - line_width) / 2
        y = top + index * line_height
        draw.text(
            (x, y),
            line,
            font=font,
            fill="white",
            stroke_width=4,
            stroke_fill="black",
        )
    return frame


def render_plan_frames(plan, folder):
    """Draw one vertical cartoon per scene, reusing the saved character."""
    folder = Path(folder)
    location = folder / "slides_auto"
    location.mkdir(parents=True, exist_ok=True)
    key = load_key() if uses_paid_pictures() else ""
    try:
        from app.characters import character_id_from_config, load_character, prompt_for, record_asset, reference_bytes
    except ImportError:
        from characters import character_id_from_config, load_character, prompt_for, record_asset, reference_bytes
    character = load_character(plan.get("character_id") or character_id_from_config())
    plan["character_id"] = character["id"]
    reference = reference_bytes(character)
    if reference:
        print(f"CHARACTER {character['id']}: saved reference", flush=True)
    else:
        print(f"CHARACTER {character['id']}: no reference image yet", flush=True)
    # The local picture model adds extra arms when it invents a gesture.
    # A locked pose reuses the checked two-arm picture for every scene.
    locked = (not uses_paid_pictures()) and bool(character.get("locked_pose")) and reference is not None
    scenes = plan["scenes"]
    frames = []
    scene_note = str(plan.get("scene_note") or "").strip()
    for scene in scenes:
        caption = " ".join(str(scene.get("body") or "").split())
        number = int(scene["number"])
        print(f"SCENE {number}/{len(scenes)}: {caption}", flush=True)
        if locked:
            raw = reference
        else:
            prompt = prompt_for(character, caption)
            if scene_note:
                prompt += " " + scene_note
            raw = generate_image(prompt, key, reference_png=reference)
            if reference is None:
                reference = raw
        picture = Image.open(io.BytesIO(raw)).convert("RGB")
        picture = picture.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
        dest = location / f"{number:02}.png"
        picture.save(dest)
        frames.append(dest)
        try:
            record_asset(character["id"], folder.name, number, dest)
        except OSError as exc:
            print("CHARACTER HISTORY:", exc, flush=True)
    return frames


def render_frames(narration, out_dir, scene_count=5):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    key = load_key() if uses_paid_pictures() else ""
    captions = group_scenes(narration, scene_count)
    frames = []
    reference = None
    for number, caption in enumerate(captions, start=1):
        print(f"SCENE {number}/{len(captions)}: {caption}", flush=True)
        raw = generate_image(scene_prompt(caption), key, reference_png=reference)
        if reference is None:
            reference = raw
        picture = Image.open(io.BytesIO(raw))
        frame = draw_caption(picture, caption)
        dest = out_dir / f"{number:02}.png"
        frame.save(dest)
        frames.append(dest)
        (out_dir / f"{number:02}.txt").write_text(caption + "\n", encoding="utf-8")
    return frames, captions


def encode_video(frames, captions, destination, audio=None):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    weights = [max(1, len(caption.split())) for caption in captions]
    total = sum(weights)
    duration = spoken_duration(audio) if audio else max(8.0, total / 2.4)
    script = destination.with_suffix(".concat.txt")
    with script.open("w", encoding="utf-8") as handle:
        for frame, weight in zip(frames, weights):
            handle.write(f"file '{Path(frame).as_posix()}'\n")
            handle.write(f"duration {duration * weight / total:.5f}\n")
        handle.write(f"file '{Path(frames[-1]).as_posix()}'\n")
    command = [
        ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "concat", "-safe", "0", "-i", str(script),
    ]
    if audio:
        command.extend(["-i", str(audio), "-t", f"{duration:.3f}", "-c:a", "aac", "-b:a", "128k"])
    else:
        command.extend(["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100", "-shortest"])
    command.extend([
        "-vf", "fps=24,format=yuv420p",
        "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(destination),
    ])
    proc = subprocess.run(command, capture_output=True, text=True)
    if proc.returncode:
        raise RuntimeError(proc.stderr[-1500:] or "ffmpeg failed")
    return destination


def spoken_duration(audio):
    ff = ffmpeg_exe()
    probe = str(Path(ff).with_name("ffprobe.exe" if ff.lower().endswith(".exe") else "ffprobe"))
    if not Path(probe).is_file():
        probe = "ffprobe"
    proc = subprocess.run(
        [probe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(audio)],
        capture_output=True, text=True,
    )
    if proc.returncode:
        raise RuntimeError(proc.stderr[-500:] or "Could not read the narration length")
    return float(proc.stdout.strip())


def render_lesson(narration, out_dir, video_path, scene_count=5, audio=None):
    frames, captions = render_frames(narration, out_dir, scene_count)
    video = encode_video(frames, captions, video_path, audio=audio)
    print("CARTOON PREVIEW:", video)
    print("NOT PUBLISHED.")
    return video


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--narration", required=True, help="Text file of the spoken lesson")
    parser.add_argument("--out", required=True, help="MP4 path to write")
    parser.add_argument("--scenes", type=int, default=5)
    parser.add_argument("--audio", help="Optional narration WAV or MP3")
    args = parser.parse_args()
    narration = Path(args.narration).read_text(encoding="utf-8").strip()
    out = Path(args.out)
    render_lesson(narration, out.parent / "frames", out, scene_count=args.scenes, audio=args.audio)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("CARTOON ERROR:", exc, file=sys.stderr)
        sys.exit(1)
