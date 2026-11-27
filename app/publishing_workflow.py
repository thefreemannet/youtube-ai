"""J3G per-job publishing preparation, metadata review and status.

No network upload occurs in this module. Approval is always checked against
current content fingerprints. An existing upload record is never overwritten.
"""

try:
    import fcntl
except ImportError:
    fcntl = None
from contextlib import contextmanager
from datetime import datetime, timezone
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
TRACKED = ('youtube', 'instagram', 'tiktok')


@contextmanager
def request_lock():
    """Serialize metadata updates against new publish requests."""
    PUBLISHER.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(PUBLISHER / '.request.lock'), os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, 'r+') as handle:
        if fcntl is not None:
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
    states, runs, metadata, enabled, retryable = {}, {}, {}, {}, {}
    for platform in TRACKED:
        record_file = RECORDS / platform / f'{job_id}.json'
        record = read_json(record_file)
        # An unreadable existing record must not be mistaken for no attempt.
        states[platform] = str(record.get('state', 'RECONCILIATION_REQUIRED' if record_file.exists() else 'NOT_UPLOADED'))
        queue_file = QUEUES / platform / f'{job_id}.json'
        request = read_json(queue_file)
        runs[platform] = str(request.get('state', 'UNKNOWN' if queue_file.exists() else 'NOT_REQUESTED'))
        retryable[platform] = upload_retryable(
            platform, record, runs[platform], record_file.exists(),
            str(request.get('error_type') or record.get('error_type') or ''),
        )
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
        'retryable': retryable,
    }


def _youtube_auth_failure(record, request_error):
    """A rejected token never created a video, so the checkbox can be used again."""
    kind = str(request_error or record.get('error_type') or '')
    return kind == 'RefreshError'


def upload_retryable(platform, record, request_state, record_exists, request_error=''):
    """A failed attempt can be sent again only when no platform id was saved."""
    if platform not in TRACKED or not isinstance(record, dict):
        return False
    if request_state in {'QUEUED', 'RUNNING'}:
        return False
    if record.get('published') is True or record.get('reel_confirmed') is True or record.get('publish_sent') is True:
        return False
    if record_exists and not record.get('state') and not record.get('job_id'):
        return False
    state = str(record.get('state') or '')
    if state in {'STARTED', 'CONTAINER_CREATED', 'UPLOADED_PROCESSING', 'PUBLISH_REQUESTED', 'UPLOADED_PRIVATE', 'UPLOADED_PUBLIC', 'PUBLISHED'}:
        return False
    if platform == 'youtube' and (record.get('youtube_video_id') or state in {'UPLOADED_PRIVATE', 'UPLOADED_PUBLIC'}):
        return False
    if platform == 'youtube' and record.get('upload_started') is True and not _youtube_auth_failure(record, request_error):
        return False
    if platform == 'instagram' and (record.get('instagram_media_id') or state == 'PUBLISHED'):
        return False
    if platform == 'tiktok' and (
        record.get('tiktok_post_id')
        or record.get('upload_started') is True
        or state in {'UPLOADED_PRIVATE', 'UPLOADED_PUBLIC', 'UPLOADED_PROCESSING', 'PUBLISHED'}
    ):
        return False
    failed_request = request_state in {'RECONCILIATION_REQUIRED', 'LAUNCH_FAILED', 'FAILED'}
    failed_record = state in {'RECONCILIATION_REQUIRED', 'FAILED', 'LAUNCH_FAILED'}
    return failed_request or failed_record


ACTIVE_UPLOADS = {'STARTED', 'CONTAINER_CREATED', 'UPLOADED_PROCESSING', 'PUBLISH_REQUESTED'}
ACTIVE_REQUESTS = {'QUEUED', 'RUNNING'}


def _worker_alive(pid):
    if not isinstance(pid, int) or pid <= 1:
        return False
    try:
        command = Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\x00', b' ').decode('utf-8', 'replace')
    except OSError:
        return False
    return 'dashboard_publish_worker' in command


def _age_seconds(stamp, clock):
    if not isinstance(stamp, str) or not stamp:
        return None
    try:
        started = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return (clock - started).total_seconds()


def _publish_proof(platform, record):
    if record.get('published') is True or record.get('publish_sent') is True or record.get('reel_confirmed') is True:
        return True
    if platform == 'youtube' and (record.get('youtube_video_id') or record.get('upload_started') is True):
        return True
    if platform == 'instagram' and record.get('instagram_media_id'):
        return True
    if platform == 'tiktok' and (record.get('tiktok_post_id') or record.get('upload_started') is True):
        return True
    return False


def _write_json(path, data):
    tmp = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as handle:
        json.dump(data, handle, indent=2)
    os.replace(tmp, path)


def reconcile_stopped_uploads(now=None):
    """Close an upload whose worker is gone so the page stops saying it is in progress.

    A video that already received a platform id, or whose publish call was sent, stays locked.
    """
    if not any((QUEUES / platform).is_dir() or (RECORDS / platform).is_dir() for platform in TRACKED):
        return []
    clock = now or datetime.now(timezone.utc)
    changed = []
    with request_lock():
        for platform in TRACKED:
            names = set()
            for folder in (QUEUES / platform, RECORDS / platform):
                if folder.is_dir():
                    names.update(path.stem for path in folder.glob('*.json') if '.failed-' not in path.name)
            for job_id in names:
                if _settle_stopped_upload(platform, job_id, clock):
                    changed.append(f'{platform}:{job_id}')
    return changed


def _settle_stopped_upload(platform, job_id, clock):
    request_path = QUEUES / platform / f'{job_id}.json'
    record_path = RECORDS / platform / f'{job_id}.json'
    request = read_json(request_path)
    record = read_json(record_path)
    request_state = str(request.get('state') or '')
    record_state = str(record.get('state') or '')
    request_busy = request_state in ACTIVE_REQUESTS
    record_busy = record_state in ACTIVE_UPLOADS
    if not request_busy and not record_busy:
        return False
    if _worker_alive(request.get('worker_pid')):
        return False
    if request_busy and not isinstance(request.get('worker_pid'), int):
        age = _age_seconds(request.get('started_utc') or request.get('requested_utc'), clock)
        if age is None or age < 180:
            return False
    proof = _publish_proof(platform, record)
    if request_busy and request_path.is_file():
        request.update(state='RECONCILIATION_REQUIRED', error_type='UploadStopped', failed_utc=clock.isoformat())
        _write_json(request_path, request)
    if record_busy and record_path.is_file():
        record['state'] = 'RECONCILIATION_REQUIRED'
        record['error_type'] = record.get('error_type') or 'UploadStopped'
        if not proof:
            record['error'] = 'The upload stopped before it finished. Check it again, then use Approve & Publish.'
        elif not record.get('error'):
            record['error'] = 'The upload stopped after a publish was requested. Confirm it is not already live before trying again.'
        _write_json(record_path, record)
    return True


def archive_failed_upload(platform, job_id):
    """Move a failed attempt aside so the same video can be submitted again."""
    if platform not in TRACKED:
        return False
    record_file = RECORDS / platform / f'{job_id}.json'
    request_file = QUEUES / platform / f'{job_id}.json'
    record = read_json(record_file)
    request = read_json(request_file)
    request_state = str(request.get('state', 'UNKNOWN' if request_file.exists() else 'NOT_REQUESTED'))
    request_error = str(request.get('error_type') or record.get('error_type') or '')
    if not upload_retryable(platform, record, request_state, record_file.exists(), request_error):
        return False
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
    for path in (record_file, request_file, QUEUES / platform / f'{job_id}.log'):
        if path.is_file():
            os.replace(path, path.with_name(f'{path.stem}.failed-{stamp}{path.suffix}'))
    return True


def prepare(job_id):
    gate_checked(job_id)
    PUBLISHER.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(PUBLISHER / '.preparation.lock'), os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, 'r+') as lock:
        if fcntl is not None:
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
        archive_failed_upload(platform, job_id)
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
