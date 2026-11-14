"""Independent visual audit. Never grants asset approval."""

import base64
import json
import sys
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

from visual_asset_manager import connect, LIBRARY, file_hash

OLLAMA = "http://192.168.120.107:11434/api/chat"
MODEL = "qwen3.5:9b"

VALID = {"match", "partial", "conflict", "uncertain"}


def audit_asset(asset_id):
    with connect() as con:
        row = con.execute(
            "SELECT * FROM assets WHERE id = ?",
            (asset_id,)
        ).fetchone()

        if row is None:
            raise ValueError("Asset not found")

        asset = dict(row)

    path = Path(asset["file_path"]).resolve()

    if not path.is_relative_to(LIBRARY.resolve()):
        raise ValueError("Invalid asset path")

    if file_hash(path) != asset["sha256"]:
        raise ValueError("Asset integrity check failed")

    sidecar = path.with_suffix(".json")
    metadata = json.loads(sidecar.read_text())
    original = metadata.get("original_metadata", {})

    with Image.open(path) as image:
        image = image.convert("RGB")
        image.thumbnail((1024, 1024))

        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=85)

    encoded = base64.b64encode(
        buffer.getvalue()
    ).decode("ascii")

    prompt = f"""
You are auditing an educational image library.

FIRST inspect the actual image.
THEN compare what you see against two untrusted claims.

PUBLISHER TITLE:
{original.get("title", "Unknown")}

PREVIOUS AI DESCRIPTION:
{asset["description"]}

The publisher title and previous AI description may be wrong.
Neither is evidence by itself.

Determine separately whether the image supports each claim.

Return JSON:
{{
  "visible_subject": "neutral description",
  "visible_evidence": ["observable feature"],
  "publisher_alignment": "match|partial|conflict|uncertain",
  "previous_ai_alignment": "match|partial|conflict|uncertain",
  "possible_identification_errors": ["issue"],
  "technical_identity_confirmed": false,
  "confidence": 0.0
}}

Rules:
- Do not invent components.
- Do not infer equipment solely from the title.
- If you cannot distinguish heating equipment from
  ventilation equipment, report uncertainty.
- Confidence reflects your assessment, not proof.
- A visually plausible object is not automatically
  a technically verified component.
"""

    payload = {
        "model": MODEL,
        "stream": False,
        "think": False,
        "format": "json",
        "options": {
            "temperature": 0,
            "num_ctx": 4096
        },
        "messages": [{
            "role": "user",
            "content": prompt,
            "images": [encoded]
        }]
    }

    with httpx.Client(timeout=180) as client:
        response = client.post(
            OLLAMA,
            json=payload
        )
        response.raise_for_status()

    result = json.loads(
        response.json()["message"]["content"]
    )

    for field in ("publisher_alignment", "previous_ai_alignment"):
        if result.get(field) not in VALID:
            raise ValueError(f"Invalid audit field: {field}")

    confidence = result.get("confidence")

    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (float, int))
        or not 0 <= confidence <= 1
    ):
        raise ValueError("Invalid confidence")

    needs_review = (
        result["publisher_alignment"] != "match"
        or result["previous_ai_alignment"] != "match"
        or result.get("technical_identity_confirmed") is not True
    )

    result["asset_id"] = asset_id
    result["needs_manual_review"] = needs_review
    result["audit_only"] = True

    report = (
        LIBRARY / "reports" /
        f"asset_{asset_id:04d}_independent_audit.json"
    )

    report.write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    print(f"\n=== ASSET {asset_id} ===")
    print("VISIBLE:", result.get("visible_subject"))
    print("PUBLISHER:", result["publisher_alignment"])
    print("PREVIOUS AI:", result["previous_ai_alignment"])
    print("CONFIDENCE:", result["confidence"])
    print("NEEDS REVIEW:", needs_review)
    print("ERRORS:", result.get("possible_identification_errors", []))
    print("REPORT:", report)


if __name__ == "__main__":
    for asset_id in (2, 3, 4):
        try:
            audit_asset(asset_id)
        except Exception as exc:
            print(f"ASSET {asset_id} AUDIT ERROR: {exc}")

    print("\nINDEPENDENT AUDIT COMPLETE")
    print("DATABASE APPROVAL STATUSES: UNCHANGED")
    print("ACTIVE PRODUCTION ENGINE: UNCHANGED")
