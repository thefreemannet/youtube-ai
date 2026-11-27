"""J3G YouTube publishing preflight.

READ-ONLY. Never uploads or publishes videos.
"""

import argparse
import json
import re
from pathlib import Path

from app.review_gate import JOBS, read_json, review_report

JOB_PATTERN = re.compile(r"\d{8}-\d{6}-[a-f0-9]{6}\Z")

REQUIRED_CONFIRMATIONS = (
    "watched_video",
    "checked_technical_claims",
    "checked_media_licenses",
)


def publishing_preflight(job_id):
    if not JOB_PATTERN.fullmatch(job_id):
        raise ValueError("Invalid job ID")

    folder = JOBS / job_id
    report = review_report(job_id)

    job = read_json(folder / "job.json")
    decision = read_json(folder / "review_decision.json")
    preview = folder / "video_auto_preview.mp4"

    reasons = []

    if job.get("status") != "APPROVED":
        reasons.append("Job has not been approved")

    if decision.get("decision") != "APPROVED":
        reasons.append("Administrator approval is missing")

    if not report["approval_current"]:
        reasons.append("Approval fingerprints are missing or outdated")

    if report["blocking_issues"]:
        reasons.extend(report["blocking_issues"])

    if not report["media"]["automated_license_checks_passed"]:
        reasons.append("Media metadata checks are incomplete")

    confirmations = decision.get("confirmations", {})

    if not isinstance(confirmations, dict):
        confirmations = {}

    for field in REQUIRED_CONFIRMATIONS:
        if confirmations.get(field) is not True:
            reasons.append(
                f"Required human confirmation missing: {field}"
            )

    if not preview.is_file() or preview.stat().st_size == 0:
        reasons.append("Final approved preview is unavailable")

    if decision.get("published") is True:
        reasons.append("Review record already indicates publication")

    return {
        "job_id": job_id,
        "ready_for_oauth_upload": not reasons,
        "upload_performed": False,
        "publication_privacy": "public",
        "approval_current": report["approval_current"],
        "human_confirmations_complete": all(
            confirmations.get(field) is True
            for field in REQUIRED_CONFIRMATIONS
        ),
        "blocking_reasons": list(dict.fromkeys(reasons)),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    args = parser.parse_args()

    result = publishing_preflight(args.job)

    print(json.dumps(result, indent=2))

    if result["ready_for_oauth_upload"]:
        print("PREFLIGHT PASSED — UPLOAD NOT PERFORMED")
    else:
        print("PUBLISHING BLOCKED — UPLOAD NOT PERFORMED")
