"""Recover a failed J3G preview from its saved narration, without re-running AI agents.

Usage on VM 111:
    .venv/bin/python -m app.recover_failed_preview 20261113-110306-e1d9dd

Never publishes, never changes jobs with existing previews or upload records.
"""
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.review_gate import JOBS, read_json, review_report, save_json
from app.workflow_dashboard import save_stage

ROOT = Path(os.environ.get('J3G_ROOT', '/opt/j3g-youtube-ai'))
JOB_ID = re.compile(r'\d{8}-\d{6}-[a-f0-9]{6}\Z')


def recover(job_id):
    if not JOB_ID.fullmatch(job_id):
        raise ValueError('Invalid job identifier')
    folder = JOBS / job_id
    job_file = folder / 'job.json'
    if not job_file.is_file():
        raise FileNotFoundError('Job does not exist')

    # Prevent simultaneous recovery attempts on the same job.
    lock_file = folder / '.preview_recovery.lock'
    fd = os.open(str(lock_file), os.O_WRONLY | os.O_CREAT, 0o600)
    with os.fdopen(fd, 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('This job is already being recovered') from exc

        job = read_json(job_file)
        if job.get('status') != 'FAILED':
            raise ValueError('Only FAILED jobs can be recovered')
        if (folder / 'video_auto_preview.mp4').exists():
            raise FileExistsError('An existing preview must never be overwritten')
        for platform in ('youtube', 'instagram'):
            if (ROOT / 'data/publisher/upload_records' / platform / f'{job_id}.json').exists():
                raise ValueError('Previously uploaded job must not be recovered')
            if (ROOT / 'data/publisher/dashboard_requests' / platform / f'{job_id}.json').exists():
                raise ValueError('Pending publication request must be reconciled first')
        narration = folder / 'narration_reviewed.txt'
        if not narration.is_file():
            narration = folder / 'narration.txt'
        if not narration.is_file() or not narration.read_text(encoding='utf-8').strip():
            raise FileNotFoundError('Saved narration is missing; refusing to rerun agents')
        quality = job.get('quality', {})
        result = str(quality.get('result', '') if isinstance(quality, dict) else '').upper()
        if 'APPROVE_FOR_HUMAN_REVIEW' not in result or 'REVISE' in result:
            raise ValueError('AI quality review does not authorize rendering')

        backup = folder / 'recovery_backups' / datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
        backup.mkdir(parents=True, mode=0o700, exist_ok=False)
        for name in ('job.json', 'production_plan.json', 'production_report_auto.json'):
            if (folder / name).is_file():
                shutil.copy2(folder / name, backup / name)
        print('JOB BACKUP:', backup, flush=True)
        print('RENDERING FROM SAVED NARRATION: no AI research, no photo downloads', flush=True)
        save_stage(folder, 'RENDERING_PREVIEW')
        command = [sys.executable, str(ROOT / 'app/production_engine_v2.py'), '--job', job_id, '--render']
        try:
            completed = subprocess.run(command, cwd=str(ROOT), text=True,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       timeout=1200, check=False)
            output = completed.stdout or ''
            print(output[-8000:], flush=True)
            with (folder / 'worker.log').open('a', encoding='utf-8') as log:
                log.write('\n=== SOLID-BACKGROUND RECOVERY ===\n' + output[-20000:] + '\n')
            if completed.returncode:
                raise RuntimeError('Solid-background renderer failed: ' + output[-1200:])
            preview = folder / 'video_auto_preview.mp4'
            if not preview.is_file() or preview.stat().st_size == 0:
                raise RuntimeError('Renderer returned success but no MP4 was produced')
            report = review_report(job_id)
            if report['blocking_issues']:
                raise RuntimeError('New preview failed review preflight: ' + '; '.join(report['blocking_issues']))
            save_stage(folder, 'PREVIEW_READY')
            updated = read_json(job_file)
            updated.pop('error', None)
            save_json(job_file, updated)
            review = review_report(job_id)
            if not review['can_approve']:
                raise RuntimeError('Video rendered, but human approval checks are still blocked')
            print('SUCCESS: PREVIEW_READY. Human review required; nothing published.', flush=True)
            print('PREVIEW:', preview, flush=True)
        except Exception as exc:
            # Keep a specific failure message visible in the dashboard.
            save_stage(folder, 'FAILED', error=str(exc)[-500:])
            raise


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: python -m app.recover_failed_preview JOB_ID')
    recover(sys.argv[1])
