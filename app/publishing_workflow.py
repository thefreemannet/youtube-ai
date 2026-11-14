"""J3G per-job publishing preparation, metadata review and status.

No network upload occurs in this module. Approval is always checked against
current content fingerprints. An existing upload record is never overwritten.
"""

import fcntl
from contextlib import contextmanager
import json
import os
from pathlib import Path

from app.youtube_publish_gate import publishing_preflight
from app.multiplatform_export import main as export_video
from app.publishing_metadata import prepare_metadata, file_hash
from app.review_gate import JOBS

ROOT = Path('/opt/j3g-youtube-ai')
PUBLISHER = ROOT / 'data/publisher'
RECORDS = PUBLISHER / 'upload_records'
QUEUES = PUBLISHER / 'dashboard_requests'
CONFIG = PUBLISHER / 'platforms.json'
PLATFORMS = ('youtube', 'instagram')


@contextmanager
def request_lock():
    """Serialize metadata updates against new publish requests."""
    PUBLISHER.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(PUBLISHER / '.request.lock'), os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, 'r+') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
    except (OSError, ValueError):
        return {}


def config():
    return read_json(CONFIG)


def gate_checked(job_id):
    gate = publishing_preflight(job_id)
    if not gate['ready_for_oauth_upload']:
        raise ValueError('Current administrator approval required: ' + '; '.join(gate['blocking_reasons']))
    return gate


def inspect(job_id):
    gate = publishing_preflight(job_id)
    folder = JOBS / job_id
    cfg = config()
    states, runs, metadata, enabled = {}, {}, {}, {}
    for platform in PLATFORMS:
        record_file = RECORDS / platform / f'{job_id}.json'
        record = read_json(record_file)
        # An unreadable existing record must not be mistaken for no attempt.
        states[platform] = str(record.get('state', 'RECONCILIATION_REQUIRED' if record_file.exists() else 'NOT_UPLOADED'))
        queue_file = QUEUES / platform / f'{job_id}.json'
        request = read_json(queue_file)
        runs[platform] = str(request.get('state', 'UNKNOWN' if queue_file.exists() else 'NOT_REQUESTED'))
        metadata_file = folder / f'{platform}_publish_metadata.json'
        data = read_json(metadata_file)
        metadata[platform] = {
            'exists': metadata_file.is_file(),
            'reviewed': data.get('reviewed_by_admin') is True,
        }
        if platform == 'youtube':
            metadata[platform].update({'title': data.get('title', ''), 'description': data.get('description', '')})
        else:
            metadata[platform].update({'caption': data.get('caption', '')})
        enabled[platform] = cfg.get('publishing_enabled') is True and cfg.get('platforms', {}).get(platform, {}).get('enabled') is True
    export = folder / 'exports/shared_publish_ready.mp4'
    return {
        'job_id': job_id,
        'review_ready': gate['ready_for_oauth_upload'],
        'blocking_reasons': gate['blocking_reasons'],
        'export_ready': export.is_file() and export.stat().st_size > 0,
        'metadata_ready': {k: v['exists'] for k, v in metadata.items()},
        'metadata': metadata,
        'platform_states': states,
        'request_states': runs,
        'platform_enabled': enabled,
    }


def prepare(job_id):
    gate_checked(job_id)
    PUBLISHER.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(PUBLISHER / '.preparation.lock'), os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, 'r+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        gate_checked(job_id)
        folder = JOBS / job_id
        if any((RECORDS / p / f'{job_id}.json').exists() for p in PLATFORMS):
            raise ValueError('An upload record already exists; preparation is locked')
        paths = {p: folder / f'{p}_publish_metadata.json' for p in PLATFORMS}
        existing = [p.is_file() for p in paths.values()]
        export = folder / 'exports/shared_publish_ready.mp4'
        if all(existing) and export.is_file() and export.stat().st_size > 0:
            return {'prepared': True, 'already_prepared': True, **inspect(job_id)}
        if any(existing):
            raise FileExistsError('Partial metadata exists; manual inspection required')
        if not export.exists():
            export_video(job_id, prepare=True)
        if not export.is_file() or not export.stat().st_size:
            raise RuntimeError('Approved video export was not created')
        gate_checked(job_id)
        prepare_metadata(job_id)
        return {'prepared': True, 'already_prepared': False, **inspect(job_id)}


def save_metadata(job_id, platform, *, title='', description='', caption='', confirm_technical=False, confirm_credits=False):
    with request_lock():
        if platform not in PLATFORMS:
            raise ValueError('Unsupported platform')
        gate_checked(job_id)
        if confirm_technical is not True or confirm_credits is not True:
            raise ValueError('Confirm factual accuracy and media attribution')
        if (RECORDS / platform / f'{job_id}.json').exists() or (QUEUES / platform / f'{job_id}.json').exists():
            raise ValueError('An upload request already exists. Metadata is locked.')
        folder = JOBS / job_id
        path = folder / f'{platform}_publish_metadata.json'
        data = read_json(path)
        if not path.is_file() or not data:
            raise FileNotFoundError('Prepare publishing files first')
        if platform == 'youtube':
            title, description = title.strip(), description.strip()
            if not (1 <= len(title) <= 100 and 1 <= len(description) <= 5000):
                raise ValueError('YouTube title 1–100 characters and description 1–5000 required')
            if 'DRAFT:' in title.upper() or 'DRAFT:' in description.upper():
                raise ValueError('Remove draft notices before approving metadata')
            video = folder / 'video_auto_preview.mp4'
            if not video.is_file() or file_hash(video) != data.get('approved_video_sha256'):
                raise ValueError('Video fingerprint changed since metadata preparation')
            data.update(title=title, description=description, reviewed_by_admin=True)
        else:
            caption = caption.strip()
            if not (1 <= len(caption) <= 2200) or 'DRAFT:' in caption.upper():
                raise ValueError('Instagram caption 1–2200 characters required; remove draft notices')
            video = folder / 'exports/shared_publish_ready.mp4'
            if not video.is_file() or file_hash(video) != data.get('video_sha256') or Path(data.get('video_path', '')).resolve() != video.resolve():
                raise ValueError('Instagram export fingerprint or path changed')
            account = read_json(PUBLISHER / 'instagram_account.json')
            if data.get('username') != account.get('username') or str(data.get('account_id')) != str(account.get('account_id')):
                raise ValueError('Instagram account mismatch')
            data.update(caption=caption, reviewed_by_admin=True)
        # Store only server-owned fields and reviewed values; no client-supplied hashes.
        temp = path.with_name(path.name + '.saving')
        fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
            gate_checked(job_id)
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)
        return inspect(job_id)
