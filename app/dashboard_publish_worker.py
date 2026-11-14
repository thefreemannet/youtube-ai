"""One-shot upload worker; created only after a logged-in explicit API request."""
import sys
from pathlib import Path

from app.dashboard_publisher import update_state, now, publish_instagram
from app.publishing_workflow import QUEUES, read_json
from app.youtube_private_uploader import upload_private


def main(platform, job_id):
    request_file = QUEUES / platform / f'{job_id}.json'
    data = read_json(request_file)
    if data.get('job_id') != job_id or data.get('platform') != platform or data.get('state') != 'QUEUED':
        raise RuntimeError('Invalid or previously processed upload request')
    data.update(state='RUNNING', started_utc=now())
    update_state(request_file, data)
    try:
        if platform == 'youtube':
            upload_private(job_id, job_id)
        elif platform == 'instagram':
            publish_instagram(job_id)
        else:
            raise RuntimeError('Unsupported publishing platform')
        data.update(state='COMPLETED', completed_utc=now())
        update_state(request_file, data)
        print('UPLOAD REQUEST COMPLETED:', job_id, platform, flush=True)
    except Exception as exc:
        data.update(state='RECONCILIATION_REQUIRED', error_type=type(exc).__name__, failed_utc=now())
        update_state(request_file, data)
        print('PUBLISHING FAILED; DO NOT RETRY UNTIL RECONCILED:', type(exc).__name__, str(exc), flush=True)
        raise


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('Usage: python -m app.dashboard_publish_worker <youtube|instagram> <job-id>')
    main(sys.argv[1], sys.argv[2])
