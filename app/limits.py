"""Resource limits for one studio job.

The studio runs one video at a time. This check refuses to start when the
disk that holds the job cannot store another preview.
"""

import os
import shutil
from pathlib import Path


def minimum_free_bytes():
    raw = os.environ.get("J3G_MIN_FREE_BYTES", str(2 * 1024 * 1024 * 1024))
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError("J3G_MIN_FREE_BYTES must be a whole number of bytes") from exc
    if value < 1:
        raise RuntimeError("J3G_MIN_FREE_BYTES must be at least 1")
    return value


def ensure_free_space(path, minimum=None):
    target = Path(path)
    minimum = minimum_free_bytes() if minimum is None else int(minimum)
    usage = shutil.disk_usage(target)
    if usage.free < minimum:
        raise RuntimeError(
            f"Not enough free disk space: {usage.free} bytes free, {minimum} bytes required"
        )
    return usage.free
