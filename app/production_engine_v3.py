"""Reusable, non-destructive J3G YouTube video preview producer.

Usage on VM 111:
    .venv/bin/python app/production_engine.py --job JOB_ID --plan
    .venv/bin/python app/production_engine.py --job JOB_ID --render

Design rules: never publish, never replace video.mp4, fail closed for missing
licensed photographs, and keep intermediate files in a job-scoped directory.
"""

import argparse
import asyncio
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

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


def keywords(text, limit=4):
    stop = {
        'what', 'which', 'when', 'where', 'why', 'how', 'does', 'do', 'and',
        'the', 'with', 'from', 'will', 'this', 'that', 'these', 'those',
        'about', 'for', 'into', 'your', 'their', 'they', 'them', 'such',
        'using', 'used', 'helps', 'help', 'have', 'has', 'can', 'are',
        'also', 'more', 'some', 'need', 'through', 'than', 'between',
        'different', 'important', 'system', 'systems', 'video', 'technicians'
    }
    words = re.findall(r'[A-Za-z][\w/-]*', text)
    result = []
    for word in words:
        key = word.casefold()
        if key not in stop and len(key) > 2 and key not in (w.casefold() for w in result):
            result.append(word)
        if len(result) >= limit:
            break
    return ' '.join(result) or 'technology'


def make_plan(folder):
    metadata = json.loads((folder / 'job.json').read_text(encoding='utf-8'))
    narration_file = folder / 'narration_reviewed.txt'
    if not narration_file.exists():
        narration_file = folder / 'narration.txt'
    narration = narration_file.read_text(encoding='utf-8').strip()
    chunks = group_scenes(narration)
    topic = metadata.get('topic') or 'Educational explanation'
    # The topic keeps image searches relevant. A human or production agent can
    # subsequently improve each scene's photo_query in production_plan.json.
    broad_query = keywords(topic, 3)
    scenes = []
    for i, body in enumerate(chunks, start=1):
        title = ' '.join(body.split()[:6]).rstrip('.,;:')
        scenes.append({
            'number': i,
            'heading': title,
            'body': body,
            'photo_query': broad_query,
            'photo_path': None,
            'license_review_required': True,
        })
    plan = {
        'schema_version': 1,
        'job_id': folder.name,
        'topic': topic,
        'narration_source': narration_file.name,
        'source_quality_status': metadata.get('status', 'UNKNOWN'),
        'review_status': 'HUMAN_REVIEW_REQUIRED',
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'scenes': scenes,
    }
    dest = folder / 'production_plan.json'
    if dest.exists():
        # Preserve manual/agent edits to scene queries and headings.
        stored = json.loads(dest.read_text(encoding='utf-8'))
        if stored.get('narration_source') == narration_file.name and len(stored.get('scenes', [])) == len(scenes):
            for old, new in zip(stored['scenes'], scenes):
                for field in ('heading', 'photo_query', 'photo_path', 'photo_query_source'):
                    if old.get(field):
                        new[field] = old[field]
    dest.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding='utf-8')
    return plan



def enrich_photo_queries(plan, folder, refresh=False):
    """Ask the Production Agent for concrete, distinct photo searches.

    Keep previously completed AI query selection stable between --plan/--render.
    Never claim photos were obtained; actual download + licensing is separate.
    """
    scenes = plan['scenes']
    if not refresh and all(
        scene.get('photo_query_source') == 'production_agent'
        and isinstance(scene.get('photo_query'), str)
        and scene['photo_query'].strip()
        for scene in scenes
    ):
        print('PHOTO SEARCH PLANNING: using saved Production Agent queries')
        return plan

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from app.agents import run_agent

    briefs = [{'number': s['number'], 'narration': s['body']} for s in scenes]
    instruction = (
        'You are choosing REAL PHOTOGRAPH search terms for an automated educational video. '
        'For EACH scene, return one distinct, practical Wikimedia Commons photograph search phrase. '
        'Focus on a clearly photographable physical object, real person, place, hardware, or equipment. '
        'Each phrase: 2 to 5 common English words, no duplicate queries. '
        'Avoid abstract concepts, protocol names, acronyms that are not everyday photo subjects, '
        'logos, diagrams, illustrations, UI screens, and cinematic concepts. '
        'For security concepts search for visible physical hardware, such as ethernet network switch, '
        'not TLS encryption. For programming concepts search for a technician, laptop or controller. '
        'Return an array of objects in result, each with number (matching the input) and search_query. '
        'Do not claim that photos were found, licensed, or downloaded. '
        'TOPIC: '+ plan['topic'] + '\nSCENES:\n' + json.dumps(briefs, ensure_ascii=False)
    )
    resp = asyncio.run(run_agent('production', instruction,
        {'task': 'scene_photo_search', 'source': 'narration', 'count': len(scenes)}))
    if not isinstance(resp, dict) or resp.get('agent') != 'production' or resp.get('status') != 'completed':
        raise ValueError('Production Agent returned an invalid response')
    items = resp.get('result')
    if isinstance(items, str):
        try:
            items = json.loads(items)
        except json.JSONDecodeError as exc:
            raise ValueError('Production Agent result is not a JSON list') from exc
    if isinstance(items, dict) and isinstance(items.get('queries'), list):
        items = items['queries']
    if not isinstance(items, list):
        raise ValueError('Production Agent result must be a list of photo searches')
    lookups = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('Production Agent produced an invalid photo query')
        try:
            number = int(item.get('number', -1))
        except (TypeError, ValueError) as exc:
            raise ValueError('Production Agent used an invalid scene number') from exc
        query = ' '.join(str(item.get('search_query', '')).split())
        if number in lookups or not (2 <= len(query.split()) <= 6) or len(query) > 100:
            raise ValueError('Production Agent produced duplicate scene numbers or invalid search terms')
        if not re.fullmatch(r"[A-Za-z0-9 \-,'/()]+", query):
            raise ValueError('Production Agent produced unsafe or non-text search terms')
        lookups[number] = query
    ids = {s['number'] for s in scenes}
    if set(lookups) != ids:
        raise ValueError(f'Production Agent returned scene numbers {sorted(lookups)}, expected {sorted(ids)}')
    if len({q.casefold() for q in lookups.values()}) != len(lookups):
        raise ValueError('Production Agent repeated photo search queries')

    for scene in scenes:
        scene['photo_query'] = lookups[scene['number']]
        scene['photo_query_source'] = 'production_agent'
        # Any previous selection is no longer valid if photo subject changed.
        scene['photo_path'] = None
        scene['license_review_required'] = True
    plan['photo_queries_generated_utc'] = datetime.now(timezone.utc).isoformat()
    (folder / 'production_plan.json').write_text(
        json.dumps(plan, indent=2, ensure_ascii=False), encoding='utf-8'
    )
    print('PHOTO SEARCH PLANNING: generated unique scene-specific queries')
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
        raise RuntimeError(f'Command failed ({proc.returncode}): {cmd[0]}\n{proc.stderr[-2000:]}')
    return proc.stdout.strip()


def ensure_photos(plan, folder):
    """Every scene must pass licensing AND real image-content checks.

    Cached photos are never trusted without revalidation for the current scene.
    The selection is isolated by job ID and scene number, so different jobs
    cannot accidentally reuse a photograph with an unrelated caption.
    """
    app_dir = ROOT / 'app'
    if str(app_dir) not in sys.path:
        sys.path.insert(0, str(app_dir))
    from visual_photo_selector import select_photo
    from visual_engine import create_background

    final = []
    for scene in plan['scenes']:
        query = (scene.get('photo_query') or '').strip()
        if not query:
            raise ValueError(f'Scene {scene["number"]}: no photographic subject')
        print(f'[PHOTO] Scene {scene["number"]}: visual verification required', flush=True)
        jpg = select_photo(plan['topic'], scene, folder)
        background = create_background(jpg)
        final.append((jpg, background))
        scene['photo_path'] = str(jpg)
        scene['license_review_required'] = True
        scene['visual_relevance_checked'] = True
    return final


def render_slides(plan, folder, backgrounds):
    location = folder / 'slides_auto'
    location.mkdir(parents=True, exist_ok=True)
    out = []
    for scene, (jpg, background) in zip(plan['scenes'], backgrounds):
        im = background.convert('RGB')
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
    return out


def audio_duration(audio):
    return float(run([
        'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', str(audio)
    ], timeout=60))


def ensure_audio(folder, plan):
    audio = folder / 'narration_auto.wav'
    if audio.is_file():
        return audio
    voice = json.loads((ROOT / 'voice_config.json').read_text(encoding='utf-8'))
    server = voice.get('server', '192.168.120.107')
    if server not in ('192.168.120.107', 'ai-gpu.lab.j3gdigital.com'):
        raise ValueError('Unexpected XTTS host: review voice_config.json')
    userhost = 'thefreemannet@' + server
    remote_name = f'{folder.name}_auto_xtts.wav'
    remote_volume = '/opt/j3gdigital/creator-studio/data/' + remote_name
    payload = json.dumps({
        'text': ' '.join((folder / plan['narration_source']).read_text(encoding='utf-8').split()),
        'language': voice.get('language', 'en'),
        'speaker': voice.get('speaker', 'Andrew Chipper'),
        'speed': voice.get('speed', 1.0),
        'output': '/data/' + remote_name,
    })
    response = run(['ssh', '-o', 'BatchMode=yes', userhost,
        'curl --fail-with-body -sS --max-time 600 -X POST http://172.18.0.9:8000/synthesize '
        "-H 'Content-Type: application/json' -d " + shlex.quote(payload)
    ], timeout=750)
    data = json.loads(response)
    if data.get('output') != '/data/' + remote_name:
        raise RuntimeError('XTTS output path mismatch')
    run(['scp', '-o', 'BatchMode=yes', f'{userhost}:{remote_volume}', str(audio)], timeout=180)
    return audio


def encode_preview(folder, plan, slides, audio):
    duration = audio_duration(audio)
    if duration <= 0:
        raise ValueError('Invalid XTTS narration duration')
    totals = [max(1, len(s['body'].split())) for s in plan['scenes']]
    weights = [x / sum(totals) for x in totals]
    concat = folder / 'slides_auto.txt'
    with concat.open('w', encoding='utf-8') as out:
        for image, weight in zip(slides, weights):
            out.write(f"file '{image}'\n")
            out.write(f'duration {duration * weight:.5f}\n')
        out.write(f"file '{slides[-1]}'\n")
    final = folder / 'video_auto_preview.mp4'
    staging = folder / 'video_auto_preview.tmp.mp4'
    run([
        'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
        '-f', 'concat', '-safe', '0', '-i', str(concat), '-i', str(audio),
        '-t', f'{duration:.3f}', '-vf', 'fps=24,format=yuv420p',
        '-c:v', 'libx264', '-preset', 'fast',
        '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', str(staging)
    ])
    actual = audio_duration(staging)
    if abs(actual - duration) > 0.5:
        raise RuntimeError(f'Audio/video duration mismatch: {actual:.2f} vs {duration:.2f}')
    os.replace(staging, final)
    return final, duration, actual


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--job', required=True, help='Explicit job ID to avoid changing the wrong job')
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--plan', action='store_true')
    modes.add_argument('--render', action='store_true')
    modes.add_argument('--verify-photos', action='store_true', help='Run image and license checks, without video assembly')
    parser.add_argument('--refresh-photo-queries', action='store_true', help='Replan photo queries with local AI')
    args = parser.parse_args()
    folder = checked_job(args.job)
    plan = make_plan(folder)
    plan = enrich_photo_queries(plan, folder, refresh=args.refresh_photo_queries)
    print('JOB:', folder.name)
    print('TOPIC:', plan['topic'])
    print('SCENES:', len(plan['scenes']))
    for scene in plan['scenes']:
        print(f"  {scene['number']}. {scene['heading']} | PHOTO QUERY: {scene['photo_query']}")
    print('PLAN:', folder / 'production_plan.json')
    if args.plan:
        print('PLAN READY. NO PHOTOS DOWNLOADED, NO VIDEO CHANGED.')
        return
    backgrounds = ensure_photos(plan, folder)
    if args.verify_photos:
        (folder / 'production_plan.json').write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding='utf-8')
        print('VISUAL REVIEW COMPLETE: all scenes passed image + license screening')
        print('NO VIDEO REBUILT. ORIGINAL PREVIEW UNCHANGED.')
        return
    slides = render_slides(plan, folder, backgrounds)
    audio = ensure_audio(folder, plan)
    video, audio_sec, video_sec = encode_preview(folder, plan, slides, audio)
    (folder / 'production_plan.json').write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding='utf-8')
    report = {
        'job_id': folder.name,
        'status': 'AWAITING_HUMAN_REVIEW',
        'published': False,
        'preview_video': str(video),
        'photographs': [s['photo_path'] for s in plan['scenes']],
        'speaker': json.loads((ROOT / 'voice_config.json').read_text())['speaker'],
        'background_opacity': json.loads((ROOT / 'visual_config.json').read_text())['background']['opacity'],
        'audio_duration_seconds': round(audio_sec, 2),
        'video_duration_seconds': round(video_sec, 2),
        'scene_timing': 'estimated_by_word_count, not word-level aligned',
        'media_license_review_required': True,
    }
    (folder / 'production_report_auto.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('PREVIEW CREATED:', video)
    print('VIDEO:', round(video_sec, 2), 'seconds; NARRATION:', round(audio_sec, 2), 'seconds')
    print('NOT PUBLISHED. HUMAN QUALITY AND LICENSE REVIEW REQUIRED.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('PRODUCTION ERROR:', exc, file=sys.stderr)
        sys.exit(1)
