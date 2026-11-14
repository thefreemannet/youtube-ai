"""Automatic image identification for the J3G Visual Asset Manager."""

import argparse
import base64
import json
import sys
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

from visual_asset_manager import (
    LIBRARY, connect, file_hash
)

OLLAMA = "http://192.168.120.107:11434/api/chat"
MODEL = "qwen3.5:9b"

PROMPT = """
Describe only what is physically visible in this photograph.

Do not assume its subject from a filename, search query,
video topic, or intended application.

Return JSON containing:
{
  "detected_subject": "specific visible subject",
  "visible_components": ["component 1", "component 2"],
  "technical_category": "equipment category",
  "uncertainties": ["anything that cannot be verified"],
  "confidence": 0.0
}

Rules:
- Do not invent equipment models or specifications.
- Do not assume an object is HVAC equipment unless visible evidence supports it.
- Describe unrelated photographs accurately.
- Distinguish components that are visible from components merely expected.
- If uncertain, use a general description.
"""

def identify(path):
    with Image.open(path) as image:
        image = image.convert("RGB")
        image.thumbnail((1024, 1024))

        buffer = BytesIO()
        image.save(buffer, "JPEG", quality=85)

    encoded = base64.b64encode(
        buffer.getvalue()
    ).decode("ascii")

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
            "content": PROMPT,
            "images": [encoded]
        }]
    }

    with httpx.Client(timeout=180) as client:
        response = client.post(OLLAMA, json=payload)
        response.raise_for_status()

    data = json.loads(
        response.json()["message"]["content"]
    )

    subject = data.get("detected_subject")
    category = data.get("technical_category")
    components = data.get("visible_components")
    confidence = data.get("confidence")

    if not isinstance(subject, str) or not subject.strip():
        raise ValueError("Missing detected subject")

    if not isinstance(category, str) or not category.strip():
        raise ValueError("Missing technical category")

    if not isinstance(components, list) or not all(
        isinstance(x, str) for x in components
    ):
        raise ValueError("Invalid components list")

    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= confidence <= 1
    ):
        raise ValueError("Invalid confidence")

    return data


def run(limit):
    with connect() as con:
        rows = con.execute(
            """
            SELECT id, file_path, sha256
            FROM assets
            WHERE description = ?
              AND subjects_json = '[]'
              AND visual_status = 'pending'
              AND technical_status = 'pending'
            ORDER BY id
            LIMIT ?
            """,
            (
                "Imported photograph pending subject identification",
                limit
            )
        ).fetchall()

    print("=== AUTOMATIC IMAGE IDENTIFICATION ===")
    print("Images selected:", len(rows))

    for row in rows:
        asset_id = row["id"]
        path = Path(row["file_path"])

        print(f"\n=== ASSET {asset_id} ===", flush=True)

        try:
            if not path.resolve().is_relative_to(LIBRARY.resolve()):
                raise ValueError("Image outside asset library")

            if not path.is_file():
                raise FileNotFoundError(path)

            if file_hash(path) != row["sha256"]:
                raise ValueError("Image hash mismatch")

            result = identify(path)

            subject = result["detected_subject"].strip()
            category = result["technical_category"].strip()
            components = [
                x.strip() for x in result["visible_components"]
                if x.strip()
            ]

            confidence = float(result["confidence"])

            print("SUBJECT:", subject)
            print("CATEGORY:", category)
            print("COMPONENTS:", ", ".join(components))
            print("CONFIDENCE:", confidence)

            report = LIBRARY / "reports" / (
                f"asset_{asset_id:04d}_identification.json"
            )

            report.write_text(
                json.dumps(result, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )

            if confidence < 0.80:
                print("RESULT: LOW CONFIDENCE — LEFT PENDING")
                continue

            subjects = list(dict.fromkeys(
                [subject, category] + components
            ))

            with connect() as con:
                con.execute(
                    """
                    UPDATE assets
                    SET description = ?,
                        subjects_json = ?
                    WHERE id = ?
                      AND sha256 = ?
                      AND description = ?
                      AND subjects_json = '[]'
                      AND visual_status = 'pending'
                      AND technical_status = 'pending'
                    """,
                    (
                        subject,
                        json.dumps(subjects, ensure_ascii=False),
                        asset_id,
                        row["sha256"],
                        "Imported photograph pending subject identification"
                    )
                )

            print("RESULT: IDENTIFICATION SAVED")
            print("APPROVAL: STILL PENDING")

        except Exception as exc:
            print("IDENTIFICATION ERROR:", str(exc)[:300])

    print("\nIMAGE IDENTIFICATION RUN COMPLETE")
    print("RIGHTS AND APPROVAL STATUSES: UNCHANGED")
    print("ACTIVE PRODUCTION ENGINE: UNCHANGED")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--limit", type=int, default=3
    )
    args = parser.parse_args()

    if not 1 <= args.limit <= 100:
        raise SystemExit("Limit must be between 1 and 100")

    run(args.limit)
