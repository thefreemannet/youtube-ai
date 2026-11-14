"""Strict, scene-aware photographic selection for J3G YouTube AI.

Only photographs with supported Wikimedia license metadata and a positive
scene-specific visual assessment can be selected. No automatic publishing.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import tempfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from PIL import Image

APP = Path(__file__).resolve().parent
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from photo_fetcher import API, ASSETS, BAD_TITLES, LICENSES, USER_AGENT, clean, meta_value, permitted
from visual_engine import create_background
from visual_relevance import check_photo

MAX_IMAGE_BYTES = 20_000_000
MAX_VISION_CHECKS = 8  # Per scene. Fail closed if none match.


def _queries(query: str, topic: str, body: str = "") -> list[str]:
    """Prioritize exact equipment, not common words or general industry photos."""
    query = ' '.join(query.split())
    q = query.casefold()
    choices = [query]
    if any(x in topic.casefold() for x in ('vav', 'variable air volume')):
        if 'filter' in q:
            choices += ['HVAC air filter', 'air handling unit filter']
        elif any(x in q for x in ('reheat', 'coil', 'heater')):
            choices += ['electric duct heater', 'HVAC reheat coil', 'duct heating coil']
        elif any(x in q for x in ('thermostat', 'sensor', 'temperature')):
            choices += ['HVAC thermostat', 'building temperature sensor']
        elif any(x in q for x in ('damper', 'actuator', 'motor')):
            choices += ['HVAC damper actuator', 'ventilation damper actuator', 'motorized air damper']
        elif any(x in q for x in ('vav', 'terminal', 'box')):
            choices += ['variable air volume terminal unit', 'VAV terminal box HVAC', 'variable air volume box']
        # No automatic fallback to generic ductwork: it can give false positives.
    else:
        # Keep the AI-selected physical subject specific for other topics.
        words = query.split()
        if len(words) >= 4:
            choices.append(' '.join(words[:3]))
    results = []
    for item in choices:
        item = ' '.join(item.split())
        if (2 <= len(item.split()) <= 9
                and re.fullmatch(r"[A-Za-z0-9 ,/()\-]+", item)
                and item.casefold() not in {x.casefold() for x in results}):
            results.append(item)
    return results[:12]


def _subject(topic: str, body: str, query: str) -> str:
    return (
        'Inspect the ACTUAL photograph, not its name or metadata. '
        f'Video topic: {topic}\n'
        f'Scene narration: {body[:950]}\n'
        f'Requested visible equipment: {query}\n'
        'APPROVE only if the photo visibly shows specific physical equipment '
        'that directly illustrates the main subject of BOTH the requested '
        'equipment and the scene narration. A broad industry connection is NOT '
        'enough. Generic ductwork does not prove a VAV terminal, damper actuator '
        'or reheat coil is visible. A server room does not prove encrypted networking. '
        'If the search query mismatches the narration, REJECT. If an item is '
        'hidden, only inferred, or ambiguous, REJECT. If uncertain, REJECT.'
    )


def _file_fingerprint(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def _save_log(folder: Path, num: int, log: list[dict], outcome: str) -> None:
    path = folder / f'visual_screening_scene_{num:02d}.json'
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps({
        'scene_number': num,
        'outcome': outcome,
        'time_utc': datetime.now(timezone.utc).isoformat(),
        'candidate_attempts': log,
    }, indent=2, ensure_ascii=False), encoding='utf-8')
    tmp.replace(path)


def _screen(path: Path, subject: str) -> dict:
    result = check_photo(path, subject)
    if not isinstance(result, dict) or result.get('approved') is not True:
        return {'approved': False, 'reason': str(result.get('reason', 'rejected')) if isinstance(result, dict) else 'invalid vision result'}
    return {'approved': True, 'confidence': result.get('confidence'), 'reason': result.get('reason', ''),
            'visible_subjects': result.get('visible_subjects', [])}


def _previous_media(folder: Path, number: int) -> tuple[set[str], set[str]]:
    """Identify Commons originals already accepted for earlier scenes of this job."""
    sources, hashes = set(), set()
    for earlier in range(1, number):
        sidecar = ASSETS / f'{folder.name}_scene_{earlier:02d}.json'
        if not sidecar.is_file():
            continue
        try:
            entry = json.loads(sidecar.read_text(encoding='utf-8'))
            if entry.get('scene_job_id') != folder.name or entry.get('scene_number') != earlier:
                continue
            if entry.get('source'):
                sources.add(entry['source'])
            digest = (entry.get('vision_gate') or {}).get('image_sha256')
            if digest:
                hashes.add(digest)
        except (ValueError, OSError):
            continue
    return sources, hashes


def select_photo(topic: str, scene: dict, folder: Path) -> Path:
    """Return job/scene-specific approved photo, otherwise raise and block rendering.

    Prior cached photos must still pass license and visual validation for the
    current scene on EVERY call. A previous selection cannot bypass the gate.
    """
    num = int(scene['number'])
    if num < 1 or num > 100:
        raise ValueError('Invalid scene number')
    query = ' '.join(str(scene.get('photo_query') or '').split())
    if not (2 <= len(query.split()) <= 10) or len(query) > 120:
        raise ValueError(f'Scene {num}: unsafe or missing photo query')
    body = str(scene.get('body') or '').strip()
    if not body:
        raise ValueError(f'Scene {num}: no narration to validate against')
    if not re.fullmatch(r'\d{8}-\d{6}-[a-f0-9]{6}', folder.name):
        raise ValueError('Invalid job folder name')
    ASSETS.mkdir(parents=True, exist_ok=True)
    target = ASSETS / f'{folder.name}_scene_{num:02d}.jpg'
    sidecar = target.with_suffix('.json')
    subject = _subject(topic, body, query)
    used_sources, used_hashes = _previous_media(folder, num)
    log: list[dict] = []

    if target.is_file() and sidecar.is_file():
        try:
            create_background(target)  # License & resolution rechecked.
            metadata = json.loads(sidecar.read_text(encoding='utf-8'))
            if metadata.get('scene_job_id') != folder.name or metadata.get('scene_number') != num:
                raise ValueError('Cached image is for a different scene/job')
            if (metadata.get('source') in used_sources or
                    _file_fingerprint(target) in used_hashes):
                raise ValueError('Photograph already used by an earlier scene')
            outcome = _screen(target, subject)  # Never trust old cached decision alone.
            log.append({'candidate': 'cached', 'title': metadata.get('title'), **outcome})
            if outcome['approved']:
                _save_log(folder, num, log, 'APPROVED')
                print(f'[VISUAL GATE] Scene {num}: cached photo revalidated', flush=True)
                return target
            print(f'[VISUAL GATE] Scene {num}: cached photo rejected, selecting replacement', flush=True)
        except (ValueError, OSError, json.JSONDecodeError, httpx.HTTPError) as exc:
            log.append({'candidate': 'cached', 'approved': False, 'reason': str(exc)[:240]})
            print(f'[VISUAL GATE] Scene {num}: cached photo failed checks', flush=True)

    checked = 0
    seen_urls = set()
    with httpx.Client(headers={'User-Agent': USER_AGENT}, timeout=45.0, follow_redirects=False) as client:
        for search in _queries(query, topic, body):
            params = {
                'action': 'query', 'format': 'json', 'generator': 'search',
                'gsrnamespace': '6', 'gsrsearch': search, 'gsrlimit': '30',
                'prop': 'imageinfo', 'iiprop': 'url|size|mime|extmetadata',
                'iiurlwidth': '1920',
                'iiextmetadatafilter': 'LicenseShortName|LicenseUrl|Artist|Credit|UsageTerms',
            }
            response = client.get(API, params=params)
            response.raise_for_status()
            result = response.json()
            if 'error' in result:
                raise RuntimeError('Wikimedia API error: ' + str(result['error']))
            pages = (result.get('query') or {}).get('pages') or {}
            print(f'[PHOTO] Scene {num}: "{search}": {len(pages)} candidates', flush=True)
            for page in pages.values():
                title = str(page.get('title') or '')
                if not title.lower().endswith(('.jpg', '.jpeg')) or any(t in title.lower() for t in BAD_TITLES):
                    continue
                info = (page.get('imageinfo') or [{}])[0]
                if info.get('mime') != 'image/jpeg' or info.get('width', 0) * info.get('height', 0) < 1920 * 1080:
                    continue
                ext = info.get('extmetadata') or {}
                license_name = meta_value(ext, 'LicenseShortName')
                author = meta_value(ext, 'Artist') or meta_value(ext, 'Credit')
                license_url = meta_value(ext, 'LicenseUrl')
                if license_name not in LICENSES or (license_name.startswith('CC BY') and (not author or not license_url)):
                    continue
                if license_name.startswith('CC BY'):
                    lic = urlsplit(license_url)
                    if lic.scheme != 'https' or lic.hostname not in ('creativecommons.org', 'www.creativecommons.org'):
                        continue
                source = str(info.get('descriptionurl') or '')
                img_url = str(info.get('thumburl') or info.get('url') or '')
                if not source.startswith('https://commons.wikimedia.org/wiki/File:') or not permitted(img_url):
                    continue
                if source in used_sources:
                    continue
                if img_url in seen_urls:
                    continue
                seen_urls.add(img_url)
                if checked >= MAX_VISION_CHECKS:
                    _save_log(folder, num, log, 'BLOCKED_NO_RELEVANT_PHOTO')
                    raise RuntimeError(f'Scene {num}: no relevant licensed photograph within {MAX_VISION_CHECKS} vision checks')
                tmp_path = None
                try:
                    with client.stream('GET', img_url, follow_redirects=False) as downloaded:
                        downloaded.raise_for_status()
                        parts = []
                        size = 0
                        for chunk in downloaded.iter_bytes():
                            size += len(chunk)
                            if size > MAX_IMAGE_BYTES:
                                raise ValueError('Image exceeds 20MB')
                            parts.append(chunk)
                    blob = b''.join(parts)
                    digest = hashlib.sha256(blob).hexdigest()
                    if digest in used_hashes:
                        continue
                    with Image.open(BytesIO(blob)) as image:
                        if image.format != 'JPEG' or image.width * image.height < 1920 * 1080:
                            continue
                        image.verify()
                    with tempfile.NamedTemporaryFile(mode='wb', prefix=f'.scene{num}_', suffix='.jpg', dir=ASSETS, delete=False) as temp:
                        temp.write(blob)
                        tmp_path = Path(temp.name)
                    checked += 1
                    verdict = _screen(tmp_path, subject)
                    log.append({'title': title, 'source': source, **verdict})
                    print(f'[VISUAL GATE] Scene {num}: candidate {checked} {"ACCEPT" if verdict["approved"] else "REJECT"} — {title[:70]}', flush=True)
                    if not verdict['approved']:
                        continue
                    metadata = {
                        'approved_for_use': True,
                        'approval_basis': 'automated license metadata and scene-specific vision screening; human review required',
                        'review_status': 'requires_final_human_license_review',
                        'license': license_name,
                        'license_url': license_url,
                        'source': source,
                        'author': author,
                        'title': title,
                        'search_query': search,
                        'usage_terms': meta_value(ext, 'UsageTerms'),
                        'attribution': f'{title} — {author or "creator not stated"} — {license_name} — {source}',
                        'scene_job_id': folder.name,
                        'scene_number': num,
                        'vision_gate': {'approved': True, 'model': 'qwen3.5:9b', 'subject': subject,
                                        'confidence': verdict.get('confidence'), 'reason': verdict.get('reason', ''),
                                        'image_sha256': digest,
                                        'checked_utc': datetime.now(timezone.utc).isoformat()},
                    }
                    # Save license metadata before creating the background; rollback on failure.
                    staged_meta = sidecar.with_suffix('.json.tmp')
                    staged_meta.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding='utf-8')
                    try:
                        tmp_path.replace(target)
                        staged_meta.replace(sidecar)
                        create_background(target)
                    except Exception:
                        staged_meta.unlink(missing_ok=True)
                        target.unlink(missing_ok=True)
                        sidecar.unlink(missing_ok=True)
                        raise
                    _save_log(folder, num, log, 'APPROVED')
                    print(f'[PHOTO APPROVED] Scene {num}: {title} [{license_name}]', flush=True)
                    return target
                except (httpx.HTTPError, OSError, ValueError) as exc:
                    log.append({'title': title, 'approved': False, 'reason': f'{type(exc).__name__}: {str(exc)[:160]}'})
                    continue
                finally:
                    if tmp_path is not None:
                        tmp_path.unlink(missing_ok=True)
    _save_log(folder, num, log, 'BLOCKED_NO_RELEVANT_PHOTO')
    raise RuntimeError(f'Scene {num}: no visually relevant licensed photograph found. Review search queries.')
