"""Find and download candidate reusable photographs from Wikimedia Commons.

Metadata screening is automated; publishing still requires checking the file page
and credit terms. Refuses unrecognized licenses and non-photographic file types.
"""
import html
import json
import re
import sys
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import httpx
from PIL import Image

from visual_engine import create_background

ROOT = Path('/opt/j3g-youtube-ai')
ASSETS = ROOT / 'assets/photos'
API = 'https://commons.wikimedia.org/w/api.php'
HVAC_QUERIES = ['air handling unit', 'HVAC equipment', 'air conditioning equipment', 'ventilation equipment']
LICENSES = {'CC0', 'CC0 1.0', 'CC BY 4.0', 'CC BY 3.0', 'CC BY 2.5', 'CC BY 2.0'}
BAD_TITLES = ('diagram', 'schematic', 'drawing', 'logo', 'icon', 'map', 'chart', 'screenshot', 'render', 'illustration')
USER_AGENT = 'J3G-YouTube-AI/1.0 (https://j3gdigital.com; educational project)'


def clean(value):
    return html.unescape(re.sub(r'<[^>]+>', ' ', str(value or ''))).strip()


def meta_value(ext, key):
    return clean((ext.get(key) or {}).get('value'))


def permitted(url):
    p = urlparse(url)
    return p.scheme == 'https' and p.hostname in ('upload.wikimedia.org', 'thumb.wikimedia.org')


def fetch_one(topic='hvac'):
    ASSETS.mkdir(parents=True, exist_ok=True)
    target = ASSETS / (re.sub(r'[^a-z0-9_-]+', '_', topic.lower()).strip('_') or 'photo')
    if topic.lower() in ('hvac', 'bacnet'):
        queries = list(HVAC_QUERIES)
    else:
        words = topic.split()
        queries = [topic]

        if len(words) > 2:
            queries += [
                ' '.join(words[:2]),
                ' '.join(words[-2:])
            ]

        if len(words) > 1:
            queries.append(words[0])

        lower = topic.casefold()

        if any(x in lower for x in ('hvac', 'air handler', 'thermostat')):
            queries += ['HVAC equipment', 'air handling unit']

        if any(x in lower for x in ('network', 'server', 'rack')):
            queries += ['computer network equipment', 'server room']

        queries = list(dict.fromkeys(
            q for q in queries if q.strip()
        ))
    with httpx.Client(headers={'User-Agent': USER_AGENT}, timeout=40.0, follow_redirects=False) as client:
        for query in queries:
            params = {
                'action': 'query', 'format': 'json', 'generator': 'search',
                'gsrnamespace': '6', 'gsrsearch': query, 'gsrlimit': '30',
                'prop': 'imageinfo', 'iiprop': 'url|size|mime|extmetadata',
                'iiextmetadatafilter': 'LicenseShortName|LicenseUrl|Artist|Credit|UsageTerms',
            }
            try:
                response = client.get(API, params=params)
                response.raise_for_status()
                body = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                print('Skipping query because the image service is unavailable:', type(exc).__name__)
                continue
            if 'error' in body:
                # A PDF or other non-image in the hit list used to fail the whole
                # search when image-only parameters were sent. Skip that query.
                print('Skipping query after Commons error')
                continue
            pages = (body.get('query') or {}).get('pages') or {}
            print(f'Search "{query}": {len(pages)} candidates')
            for page in pages.values():
                title = page.get('title', '')
                info = (page.get('imageinfo') or [{}])[0]
                mime = str(info.get('mime') or '')
                if title.lower().endswith('.pdf') or mime == 'application/pdf':
                    continue
                if mime != 'image/jpeg' or not title.lower().endswith(('.jpg', '.jpeg')):
                    continue
                if any(term in title.lower() for term in BAD_TITLES):
                    continue
                if info.get('width', 0) * info.get('height', 0) < 1920 * 1080:
                    continue
                ext = info.get('extmetadata') or {}
                license_name = meta_value(ext, 'LicenseShortName')
                if license_name not in LICENSES:
                    continue
                creator = meta_value(ext, 'Artist') or meta_value(ext, 'Credit')
                if license_name.startswith('CC BY') and not creator:
                    continue
                source_url = info.get('descriptionurl', '')
                license_url = meta_value(ext, 'LicenseUrl')
                image_url = info.get('thumburl') or info.get('url') or ''
                if not source_url.startswith('https://commons.wikimedia.org/'):
                    continue
                if not permitted(image_url):
                    continue
                try:
                    with client.stream('GET', image_url, follow_redirects=False) as img_response:
                        img_response.raise_for_status()
                        chunks, size = [], 0
                        for chunk in img_response.iter_bytes():
                            size += len(chunk)
                            if size > 20_000_000:
                                raise ValueError('Image exceeds 20 MB')
                            chunks.append(chunk)
                    blob = b''.join(chunks)
                    with Image.open(BytesIO(blob)) as picture:
                        if picture.format != 'JPEG' or picture.width * picture.height < 1920 * 1080:
                            continue
                        picture.verify()
                    jpg = target.with_suffix('.jpg')
                    sidecar = target.with_suffix('.json')
                    metadata = {
                        'approved_for_use': True,
                        'approval_basis': 'automated license metadata screening; manual publishing review still required',
                        'review_status': 'requires_final_human_license_review',
                        'license': license_name, 'license_url': license_url,
                        'source': source_url, 'author': creator,
                        'title': title, 'search_query': query,
                        'usage_terms': meta_value(ext, 'UsageTerms'),
                        'attribution': f'{title} — {creator or "creator not stated"} — {license_name} — {source_url}',
                    }
                    jpg.write_bytes(blob)
                    sidecar.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding='utf-8')
                    preview = target.parent / (target.name + '_preview.png')
                    create_background(jpg).save(preview)
                    print('PHOTO DOWNLOADED:', jpg)
                    print('LICENSE:', license_name)
                    print('SOURCE:', source_url)
                    print('BACKGROUND PREVIEW:', preview)
                    print('PUBLISHING REVIEW: REQUIRED')
                    return 0
                except (httpx.HTTPError, ValueError, OSError) as ex:
                    print('Skipping image:', type(ex).__name__)
        print('NO APPROVED CANDIDATE FOUND. No copyrighted substitute used.')
        return 2


if __name__ == '__main__':
    try:
        sys.exit(fetch_one(sys.argv[1] if len(sys.argv) > 1 else 'hvac'))
    except (httpx.HTTPError, ValueError, OSError, RuntimeError) as exc:
        print('PHOTO SOURCE ERROR:', str(exc))
        sys.exit(1)
