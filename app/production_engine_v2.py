"""Reusable, non-destructive J3G YouTube video preview producer.

Usage on VM 111:
    .venv/bin/python app/production_engine_v2.py --job JOB_ID --plan
    .venv/bin/python app/production_engine_v2.py --job JOB_ID --render

Design rules: draw the existing text slides above an optional cached
photograph, never download images while rendering, never publish, never
overwrite an existing preview, and keep intermediate files in the job directory.
"""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

try:
    from app.media_validate import validate_preview
    from app.background_images import compose_scene_background, prepare_plan_backgrounds
    from app.categories import category_info, normalize_category
except ImportError:  # running as a script adds app/ to sys.path
    from media_validate import validate_preview
    from background_images import compose_scene_background, prepare_plan_backgrounds
    from categories import category_info, normalize_category

ROOT = Path(os.environ.get('J3G_ROOT', '/opt/j3g-youtube-ai'))
JOBS = ROOT / 'data' / 'jobs'
FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
BOLD = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'


def checked_job(job_id):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{1,100}', job_id):
        raise ValueError('Invalid job ID')
    folder = JOBS / job_id
    if not folder.is_dir() or not (folder / 'job.json').is_file():
        raise FileNotFoundError(f'Job not found: {folder}')
    return folder


def sentences(text):
    parts = re.split(r'(?<=[.!?])\s+(?=[\w"“])', ' '.join(text.split()))
    return [p.strip() for p in parts if p.strip()]


def group_scenes(text, count=5):
    units = sentences(text)
    if not units:
        raise ValueError('Narration is empty')
    count = min(count, len(units))
    # Greedily balance five contiguous groups by approximate spoken word count.
    groups = []
    idx = 0
    for slot in range(count):
        left = count - slot
        end = len(units) - (left - 1)
        words_left = sum(len(s.split()) for s in units[idx:])
        target = words_left / left
        best = idx + 1
        best_delta = float('inf')
        for j in range(idx + 1, end + 1):
            n = sum(len(s.split()) for s in units[idx:j])
            delta = abs(n - target)
            if delta < best_delta:
                best, best_delta = j, delta
        groups.append(' '.join(units[idx:best]))
        idx = best
    assert idx == len(units)
    return groups


def make_plan(folder):
    # Never rewrite the approved plan for a video already rendered. This
    # preserves legacy photograph-based approvals and their SHA-256 fingerprints.
    existing_preview = folder / 'video_auto_preview.mp4'
    existing_plan = folder / 'production_plan.json'
    if existing_preview.is_file():
        if not existing_plan.is_file():
            raise FileNotFoundError('Rendered preview has no production plan')
        return json.loads(existing_plan.read_text(encoding='utf-8'))
    metadata = json.loads((folder / 'job.json').read_text(encoding='utf-8'))
    narration_file = folder / 'narration_reviewed.txt'
    if not narration_file.exists():
        narration_file = folder / 'narration.txt'
    narration = narration_file.read_text(encoding='utf-8').strip()
    chunks = group_scenes(narration)
    topic = metadata.get('topic') or 'Educational explanation'
    if str(metadata.get('language') or '').lower() == 'es':
        try:
            from app.spanish_titles import display_title
        except ImportError:
            from spanish_titles import display_title
        topic = display_title(topic, 'es', narration)
    scenes = []
    for i, body in enumerate(chunks, start=1):
        title = ' '.join(body.split()[:6]).rstrip('.,;:')
        scenes.append({
            'number': i,
            'heading': title,
            'body': body,
        })
    info = category_info(metadata.get('category'))
    plan = {
        'schema_version': 2,
        'job_id': folder.name,
        'topic': topic,
        'language': 'es' if str(metadata.get('language') or '').lower() == 'es' else 'en',
        'category': normalize_category(metadata.get('category')),
        'character_id': info['character_id'],
        'scene_note': info.get('scene_note') or '',
        'narration_source': narration_file.name,
        'source_quality_status': metadata.get('status', 'UNKNOWN'),
        'review_status': 'HUMAN_REVIEW_REQUIRED',
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'scenes': scenes,
    }
    dest = folder / 'production_plan.json'
    if dest.exists():
        # Preserve previously edited headings (including for failed jobs),
        # but drop old photo queries and paths. No external images are used.
        stored = json.loads(dest.read_text(encoding='utf-8'))
        if stored.get('narration_source') == narration_file.name and len(stored.get('scenes', [])) == len(scenes):
            fields = (
                'heading', 'background_image', 'background_opacity',
                'background_source', 'background_license', 'background_attribution',
            )
            for old, new in zip(stored['scenes'], scenes):
                for field in fields:
                    if old.get(field):
                        new[field] = old[field]
    prepare_plan_backgrounds(plan, folder, ROOT)
    dest.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding='utf-8')
    return plan



def panel(draw, rect, fill='#17263b', border='#3b82f6', radius=26):
    draw.rounded_rectangle(rect, radius=radius, fill=fill, outline=border, width=3)


def fit(draw, text, box, max_size=44, min_size=17, bold=False, color='#f8fafc'):
    x, y, w, h = box
    for size in range(max_size, min_size - 1, -1):
        font = ImageFont.truetype(BOLD if bold else FONT, size)
        lines = []
        for paragraph in text.split('\n'):
            current = ''
            for word in paragraph.split():
                next_text = (current + ' ' + word).strip()
                bounds = draw.textbbox((0, 0), next_text, font=font)
                if bounds[2] - bounds[0] <= w:
                    current = next_text
                else:
                    if current:
                        lines.append(current)
                    current = word
            if current:
                lines.append(current)
        formatted = '\n'.join(lines)
        bounds = draw.multiline_textbbox((0, 0), formatted, font=font, spacing=10, align='center')
        tw = bounds[2] - bounds[0]
        th = bounds[3] - bounds[1]
        if tw <= w and th <= h:
            draw.multiline_text(
                (x + (w - tw) / 2 - bounds[0], y + (h - th) / 2 - bounds[1]),
                formatted, font=font, fill=color, spacing=10, align='center'
            )
            return size
    raise ValueError(f'Text does not fit in {box}: {text[:70]}')


def run(cmd, timeout=900):
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode:
        detail = ((proc.stderr or '') + '\n' + (proc.stdout or '')).strip()
        raise RuntimeError(f'Command failed ({proc.returncode}): {cmd[0]}\n{detail[-2000:]}')
    return proc.stdout.strip()


def render_slides(plan, folder):
    location = folder / 'slides_auto'
    location.mkdir(parents=True, exist_ok=True)
    out = []
    used = []
    roots = [folder, folder / 'backgrounds', folder / 'background_library', ROOT / 'assets' / 'backgrounds']
    for scene in plan['scenes']:
        # Text, panels, and positions below are unchanged. The photograph is
        # only the base layer and is omitted when it is missing or invalid.
        im, image_path = compose_scene_background(scene, plan, roots)
        if image_path:
            used.append(scene.get('background_image') or image_path)
        draw = ImageDraw.Draw(im)
        panel(draw, (34, 35, 686, 122), fill='#123b66', border='#123b66', radius=18)
        fit(draw, 'J3G  TECH  EXPLAINED', (58, 52, 604, 54), 30, 22, bold=True)
        fit(draw, plan['topic'], (44, 155, 632, 118), 46, 22, bold=True)
        panel(draw, (65, 325, 655, 1020))
        fit(draw, scene['heading'], (104, 369, 512, 168), 36, 22, bold=True, color='#7dd3fc')
        draw.line((110, 566, 610, 566), fill='#334155', width=3)
        fit(draw, scene['body'], (104, 605, 512, 340), 34, 18)
        draw.line((60, 1150, 660, 1150), fill='#334155', width=2)
        fit(draw, f'SCENE {scene["number"]} OF {len(plan["scenes"])}  |  HUMAN REVIEW REQUIRED',
            (60, 1173, 600, 45), 21, 16, color='#b6c6db')
        dest = location / f'{scene["number"]:02}.png'
        im.save(dest)
        out.append(dest)
    return out, used


def audio_duration(audio):
    return float(run([
        'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', str(audio)
    ], timeout=60))


def ensure_audio(folder, plan):
    audio = folder / 'narration_auto.wav'
    if audio.is_file() and not (folder / 'voice_fallback.txt').is_file():
        return audio
    audio.unlink(missing_ok=True)
    voice = json.loads((ROOT / 'voice_config.json').read_text(encoding='utf-8'))
    server = voice.get('server', '192.168.120.107')
    if server not in ('192.168.120.107', 'ai-gpu.lab.j3gdigital.com'):
        raise ValueError('Unexpected XTTS host: review voice_config.json')
    userhost = 'thefreemannet@' + server
    remote_name = f'{folder.name}_auto_xtts.wav'
    remote_volume = '/opt/j3gdigital/creator-studio/data/' + remote_name
    speaker = voice.get('speaker', 'Andrew Chipper')
    language = plan.get('language') or voice.get('language', 'en')
    try:
        from app.spoken_terms import spoken_narration
    except ImportError:
        from spoken_terms import spoken_narration
    spoken = spoken_narration(
        ' '.join((folder / plan['narration_source']).read_text(encoding='utf-8').split()),
        language,
    )
    payload = json.dumps({
        'text': spoken,
        'language': language,
        'speaker': speaker,
        'speed': voice.get('speed', 1.0),
        'output': '/data/' + remote_name,
    })
    # The container address on ai-gpu changes when that machine's services restart.
    remote = (
        "ip=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' j3g-ai-tts-xtts) && "
        'test -n "$ip" && '
        'curl --fail-with-body -sS --max-time 600 -X POST "http://$ip:8000/synthesize" '
        "-H 'Content-Type: application/json' -d " + shlex.quote(payload)
    )
    print('XTTS:', server, 'speaker', speaker, plan.get('language') or 'en', flush=True)
    response = run(['ssh', '-o', 'BatchMode=yes', userhost, remote], timeout=750)
    data = json.loads(response)
    if data.get('output') != '/data/' + remote_name:
        raise RuntimeError('XTTS output path mismatch')
    run(['scp', '-o', 'BatchMode=yes', f'{userhost}:{remote_volume}', str(audio)], timeout=180)
    (folder / 'voice_fallback.txt').unlink(missing_ok=True)
    return audio


def animation_mode():
    """Still frames are the default. A slow pan remains available in the config."""
    try:
        raw = json.loads((ROOT / 'visual_config.json').read_text(encoding='utf-8'))
        mode = str((raw.get('animation') or {}).get('mode') or 'still').strip().lower()
    except (OSError, ValueError, TypeError):
        mode = 'still'
    if mode not in ('still', 'kenburns'):
        return 'still'
    return mode


def motion_clip(image, seconds, dest, direction):
    seconds = max(0.4, float(seconds))
    dur = f'{seconds:.3f}'
    if direction == 0:
        x_expr = f'(iw-720)*t/{dur}'
        y_expr = '(ih-1280)*0.2'
    elif direction == 1:
        x_expr = f'(iw-720)*(1-t/{dur})'
        y_expr = '(ih-1280)*0.2'
    else:
        x_expr = '(iw-720)*0.5'
        y_expr = f'(ih-1280)*t/{dur}'
    run([
        'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
        '-loop', '1', '-framerate', '24', '-i', str(image),
        '-t', dur,
        '-vf', (
            'scale=806:1434:force_original_aspect_ratio=increase,'
            f'crop=720:1280:{x_expr}:{y_expr},fps=24,format=yuv420p'
        ),
        '-c:v', 'libx264', '-preset', 'veryfast', '-pix_fmt', 'yuv420p',
        str(dest),
    ], timeout=300)


def encode_preview(folder, plan, slides, audio):
    duration = audio_duration(audio)
    if duration <= 0:
        raise ValueError('Invalid XTTS narration duration')
    totals = [max(1, len(s['body'].split())) for s in plan['scenes']]
    weights = [x / sum(totals) for x in totals]
    scene_seconds = [duration * weight for weight in weights]
    sources = list(slides)
    used_motion = False
    if animation_mode() == 'kenburns':
        motion_dir = folder / 'motion_auto'
        motion_dir.mkdir(parents=True, exist_ok=True)
        clips = []
        try:
            for index, (image, seconds) in enumerate(zip(slides, scene_seconds)):
                clip = motion_dir / f'{index + 1:02}.mp4'
                print(f'MOTION {index + 1}/{len(slides)}: {seconds:.1f}s', flush=True)
                motion_clip(image, seconds, clip, index % 3)
                clips.append(clip)
            sources = clips
            used_motion = True
        except Exception as exc:
            print('MOTION FALLBACK: still frames.', exc, flush=True)
            sources = list(slides)
            used_motion = False
    concat = folder / 'slides_auto.txt'
    with concat.open('w', encoding='utf-8') as out:
        if used_motion:
            for clip in sources:
                out.write(f"file '{clip}'\n")
        else:
            for image, seconds in zip(sources, scene_seconds):
                out.write(f"file '{image}'\n")
                out.write(f'duration {seconds:.5f}\n')
            out.write(f"file '{sources[-1]}'\n")
    plan['animation_mode'] = 'kenburns' if used_motion else 'still'
    narration_name = plan.get('narration_source') or 'narration.txt'
    narration_text = (folder / narration_name).read_text(encoding='utf-8')
    try:
        from app.subtitles import write_subtitles
    except ImportError:
        from subtitles import write_subtitles
    subtitles = write_subtitles(folder, narration_text, duration)
    plan['subtitles'] = str(subtitles)
    print('SUBTITLES:', subtitles, flush=True)
    video_filter = f"fps=24,subtitles={subtitles},format=yuv420p"
    final = folder / 'video_auto_preview.mp4'
    staging = folder / 'video_auto_preview.tmp.mp4'
    run([
        'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
        '-f', 'concat', '-safe', '0', '-i', str(concat), '-i', str(audio),
        '-t', f'{duration:.3f}', '-vf', video_filter,
        '-c:v', 'libx264', '-preset', 'fast',
        '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', str(staging)
    ])
    actual = audio_duration(staging)
    if abs(actual - duration) > 0.5:
        staging.unlink(missing_ok=True)
        raise RuntimeError(f'Audio/video duration mismatch: {actual:.2f} vs {duration:.2f}')
    try:
        validate_preview(staging)
    except Exception:
        staging.unlink(missing_ok=True)
        raise
    os.replace(staging, final)
    return final, duration, actual


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--job', required=True, help='Explicit job ID to avoid changing the wrong job')
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--plan', action='store_true')
    modes.add_argument('--render', action='store_true')
    args = parser.parse_args()
    folder = checked_job(args.job)
    # Protect prior previews and their human approvals from accidental changes.
    if args.render and (folder / 'video_auto_preview.mp4').exists():
        raise FileExistsError('Preview already exists; refusing to overwrite')
    plan = make_plan(folder)
    print('JOB:', folder.name)
    print('TOPIC:', plan['topic'])
    print('SCENES:', len(plan['scenes']))
    if plan.get('background_mode') == 'cartoon':
        print('BACKGROUND: vertical cartoon technician, 720 by 1280')
    elif plan.get('background_mode') == 'photo':
        print('BACKGROUND: cached photograph at configured opacity, solid fallback')
    else:
        print('BACKGROUND: solid dark, no external photos')
    for scene in plan['scenes']:
        print(f"  {scene['number']}. {scene['heading']}")
    print('PLAN:', folder / 'production_plan.json')
    if args.plan:
        print('PLAN READY. NO PHOTOS DOWNLOADED, NO VIDEO CHANGED.')
        return
    if plan.get('background_mode') == 'cartoon':
        try:
            from app.cartoon_scenes import render_plan_frames
        except ImportError:
            from cartoon_scenes import render_plan_frames
        slides = render_plan_frames(plan, folder)
        used_photos = []
    else:
        slides, used_photos = render_slides(plan, folder)
    audio = ensure_audio(folder, plan)
    video, audio_sec, video_sec = encode_preview(folder, plan, slides, audio)
    (folder / 'production_plan.json').write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding='utf-8')
    report = {
        'job_id': folder.name,
        'status': 'AWAITING_HUMAN_REVIEW',
        'published': False,
        'preview_video': str(video),
        'photographs': used_photos,
        'background_mode': plan.get('background_mode') or 'solid',
        'speaker': 'Local preview voice' if (folder / 'voice_fallback.txt').is_file() else json.loads((ROOT / 'voice_config.json').read_text())['speaker'],
        'background_opacity': plan.get('background_opacity') if plan.get('background_mode') == 'photo' else 0,
        'audio_duration_seconds': round(audio_sec, 2),
        'video_duration_seconds': round(video_sec, 2),
        'min_seconds': 60,
        'animation_mode': plan.get('animation_mode') or 'still',
        'character_id': plan.get('character_id'),
        'subtitles': plan.get('subtitles') or str(folder / 'subtitles.ass'),
        'scene_timing': 'estimated_by_word_count, not word-level aligned',
        'media_license_review_required': bool(used_photos),
    }
    (folder / 'production_report_auto.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('PREVIEW CREATED:', video)
    print('VIDEO:', round(video_sec, 2), 'seconds; NARRATION:', round(audio_sec, 2), 'seconds')
    print('ANIMATION:', plan.get('animation_mode') or 'still')
    if audio_sec < 60:
        print('DURATION WARNING: narration is under 60 seconds.')
    print('NOT PUBLISHED. HUMAN TECHNICAL AND VIDEO REVIEW REQUIRED.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('PRODUCTION ERROR:', exc, file=sys.stderr)
        sys.exit(1)
