"""Explicit per-platform publishing requests and generic Instagram Reel publishing.

No automatic retries. Existing upload records and dashboard requests block repeats,
including when a prior API attempt has an uncertain result.
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests

from app.publishing_workflow import (
    ROOT, PUBLISHER, RECORDS, QUEUES, archive_failed_upload, config, gate_checked, read_json, request_lock,
)
from app.review_gate import JOBS
from app.publishing_metadata import file_hash
from app.youtube_private_uploader import check as check_youtube
from app.instagram_reel_stage import checked_response, reel_upload_can_retry

API = 'https://graph.facebook.com/v26.0'


def now():
    return datetime.now(timezone.utc).isoformat()


def update_state(path, data):
    tmp = path.with_name(path.name + '.tmp')
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def platform_check(job_id, platform):
    if platform not in ('youtube', 'instagram', 'tiktok'):
        raise ValueError('Unsupported platform')
    gate_checked(job_id)
    cfg = config()
    if cfg.get('publishing_enabled') is not True or cfg.get('platforms', {}).get(platform, {}).get('enabled') is not True:
        raise ValueError(f'{platform.title()} publishing is disabled in platform settings')
    if (RECORDS / platform / f'{job_id}.json').exists():
        raise FileExistsError('Previous platform upload attempt exists; manual reconciliation required')
    folder = JOBS / job_id
    metadata_file = folder / f'{platform}_publish_metadata.json'
    data = read_json(metadata_file)
    if data.get('reviewed_by_admin') is not True:
        raise ValueError('Review and approve platform metadata first')
    if platform == 'youtube':
        outcome = check_youtube(job_id)
        if not outcome['ready']:
            raise ValueError('YouTube preflight: ' + '; '.join(outcome['blocking_reasons']))
    elif platform == 'tiktok':
        video = folder / 'exports/shared_publish_ready.mp4'
        if (not video.is_file() or not video.stat().st_size
                or data.get('video_sha256') != file_hash(video)
                or Path(data.get('video_path', '')).resolve() != video.resolve()):
            raise ValueError('TikTok video integrity validation failed')
        if (data.get('platform') != 'tiktok'
                or data.get('reviewed_by_admin') is not True
                or not isinstance(data.get('caption'), str)
                or not (1 <= len(data['caption']) <= 2200)
                or 'DRAFT:' in data['caption'].upper()):
            raise ValueError('TikTok metadata validation failed')
        token_file = PUBLISHER / 'credentials/tiktok_token.json'
        if not token_file.is_file() or token_file.stat().st_mode & 0o077:
            raise ValueError('TikTok account is not connected')
    else:
        video = folder / 'exports/shared_publish_ready.mp4'
        account = read_json(PUBLISHER / 'instagram_account.json')
        if (not video.is_file() or not video.stat().st_size
                or data.get('video_sha256') != file_hash(video)
                or Path(data.get('video_path', '')).resolve() != video.resolve()):
            raise ValueError('Instagram video integrity validation failed')
        if (data.get('platform') != 'instagram' or data.get('media_type') != 'REELS'
                or data.get('published') is not False or data.get('username') != account.get('username')
                or str(data.get('account_id')) != str(account.get('account_id'))
                or not str(account.get('account_id', '')).isdecimal()
                or not isinstance(data.get('caption'), str)
                or not (1 <= len(data['caption']) <= 2200)
                or 'DRAFT:' in data['caption'].upper()):
            raise ValueError('Instagram metadata validation failed')
        token_file = PUBLISHER / 'credentials/instagram_access_token.txt'
        if not token_file.is_file() or token_file.stat().st_mode & 0o077:
            raise ValueError('Instagram access token missing or permissions too open')
    return data


def enqueue(job_id, platform, confirmation):
    with request_lock():
        if job_id != confirmation:
            raise ValueError('Explicit job ID confirmation does not match')
        archive_failed_upload(platform, job_id)
        platform_check(job_id, platform)
        directory = QUEUES / platform
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o700)
        request_path = directory / f'{job_id}.json'
        state = {'job_id': job_id, 'platform': platform, 'state': 'QUEUED', 'requested_utc': now()}
        fd = os.open(str(request_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as handle:
            json.dump(state, handle, indent=2)
        # Request exists before spawning: double-clicks/races cannot start 2 jobs.
        try:
            log_path = directory / f'{job_id}.log'
            with log_path.open('ab') as log:
                subprocess.Popen(
                    [sys.executable, '-m', 'app.dashboard_publish_worker', platform, job_id],
                    cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                    start_new_session=True, close_fds=True,
                )
        except Exception as exc:
            state['state'] = 'LAUNCH_FAILED'
            state['error'] = type(exc).__name__
            update_state(request_path, state)
            raise RuntimeError('Could not launch publisher; manual reconciliation required') from exc
        return {'job_id': job_id, 'platform': platform, 'request_state': 'QUEUED', 'upload_confirmed': False}


def publish_instagram(job_id):
    data = platform_check(job_id, 'instagram')
    folder = JOBS / job_id
    video = folder / 'exports/shared_publish_ready.mp4'
    token = (PUBLISHER / 'credentials/instagram_access_token.txt').read_text(encoding='utf-8').strip()
    if not token:
        raise RuntimeError('Instagram token empty')
    records_dir = RECORDS / 'instagram'
    records_dir.mkdir(parents=True, exist_ok=True)
    records_dir.chmod(0o700)
    record_path = records_dir / f'{job_id}.json'
    state = {'job_id': job_id, 'platform': 'instagram', 'state': 'STARTED',
             'account': data['username'], 'video_sha256': data['video_sha256'],
             'created_utc': now(), 'published': False}
    fd = os.open(str(record_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)
    headers = {'Authorization': f'Bearer {token}'}
    account = str(data['account_id'])
    try:
        with requests.Session() as session:
            container_id = ''
            for attempt in range(6):
                response = session.post(f'{API}/{account}/media', headers=headers,
                    data={'media_type': 'REELS', 'upload_type': 'resumable',
                          'caption': data['caption'], 'share_to_feed': 'false'}, timeout=(15, 45))
                result = checked_response(response)
                container_id, upload_uri = str(result.get('id', '')), result.get('uri', '')
                if not container_id.isdecimal() or not isinstance(upload_uri, str):
                    raise RuntimeError('Meta did not return a valid container')
                state.update(container_id=container_id, state='CONTAINER_CREATED', upload_attempt=attempt + 1)
                update_state(record_path, state)
                target = urlsplit(upload_uri)
                if (target.scheme != 'https' or target.hostname != 'rupload.facebook.com'
                        or target.username or target.password or target.port not in (None, 443)):
                    raise RuntimeError('Unsafe Instagram upload destination')
                gate_checked(job_id)
                if file_hash(video) != data['video_sha256']:
                    raise RuntimeError('Instagram video changed during upload preparation')
                file_size = str(video.stat().st_size)
                with video.open('rb') as input_file:
                    payload = input_file.read()
                if str(len(payload)) != file_size:
                    raise RuntimeError('Instagram video size changed while reading it')
                try:
                    response = session.post(upload_uri,
                        headers={'Authorization': f'OAuth {token}', 'offset': '0',
                                 'file_size': file_size,
                                 'Content-Type': 'application/octet-stream',
                                 'Content-Length': file_size},
                        data=payload, timeout=(15, 180))
                    result = checked_response(response)
                except RuntimeError as exc:
                    if not reel_upload_can_retry(exc, attempt):
                        raise
                    time.sleep(12)
                    continue
                if result.get('success') is not True:
                    raise RuntimeError('Meta did not confirm binary upload')
                break
            else:
                raise RuntimeError('Meta did not confirm binary upload')
            state['state'] = 'UPLOADED_PROCESSING'
            update_state(record_path, state)
            # Processing is asynchronous at Meta. Poll, never create a second container.
            for attempt in range(60):
                response = session.get(f'{API}/{container_id}', headers=headers,
                    params={'fields': 'status_code'}, timeout=(15, 30))
                result = checked_response(response)
                status = result.get('status_code', 'UNKNOWN')
                state['media_status'] = status
                update_state(record_path, state)
                if status == 'FINISHED':
                    break
                if status in ('ERROR', 'EXPIRED'):
                    raise RuntimeError(f'Meta reported media status {status}')
                time.sleep(5)
            else:
                raise RuntimeError('Meta processing timed out; reconcile before retry')
            gate_checked(job_id)
            state['state'] = 'PUBLISH_REQUESTED'
            state['publish_sent'] = True
            update_state(record_path, state)
            response = session.post(f'{API}/{account}/media_publish', headers=headers,
                data={'creation_id': container_id}, timeout=(15, 60))
            result = checked_response(response)
            media_id = str(result.get('id', ''))
            if not media_id.isdecimal():
                raise RuntimeError('Meta did not return a publication ID')
            state['instagram_media_id'] = media_id
            update_state(record_path, state)
            from app.instagram_reel_check import reel_confirmation
            confirmation = None
            last_error = 'Instagram did not confirm this video is on the Reel'
            for _attempt in range(12):
                response = session.get(
                    f'{API}/{media_id}',
                    headers=headers,
                    params={'fields': 'id,media_type,media_product_type,permalink'},
                    timeout=(15, 30),
                )
                try:
                    confirmation = reel_confirmation(media_id, checked_response(response))
                    break
                except RuntimeError as exc:
                    last_error = str(exc)
                    time.sleep(5)
            if confirmation is None:
                raise RuntimeError(last_error)
            state.update(
                state='PUBLISHED',
                published=True,
                instagram_media_id=media_id,
                reel_confirmed=True,
                reel_permalink=confirmation['permalink'],
                media_product_type='REELS',
                completed_utc=now(),
            )
            update_state(record_path, state)
            return state
    except Exception as exc:
        state.update(state='RECONCILIATION_REQUIRED', error_type=type(exc).__name__)
        if isinstance(exc, RuntimeError) and 'token' not in str(exc).lower():
            state['error'] = str(exc)[:240]
        update_state(record_path, state)
        raise
