import base64
import json
import sys
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image, ImageOps

OLLAMA = "http://192.168.120.107:11434/api/chat"
MODEL = "qwen3.5:9b"


def check_photo(image_path, required_subject):
    path = Path(image_path)

    with Image.open(path) as original:
        image = ImageOps.exif_transpose(original)
        image = image.convert("RGB")
        image.thumbnail((1024, 1024))

        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=85)

    encoded = base64.b64encode(
        buffer.getvalue()
    ).decode("ascii")

    prompt = f"""
You are a strict photographic relevance inspector.

Required photographic subject:
{required_subject}

Examine the actual IMAGE, not its filename or search metadata.

Determine whether the image visibly depicts the required
physical subject.

Rules:
- Reject unrelated photographs.
- Reject ambiguous matches.
- Reject photographs showing only a similarly named place.
- Do not infer invisible equipment.
- Generic association is insufficient.
- When uncertain, reject.
- Do not invent visual details.

Return JSON with exactly these fields:
{{
  "visible_subjects": ["object 1", "object 2"],
  "relevant": true,
  "confidence": 0.95,
  "reason": "brief explanation"
}}

Use relevant=false when evidence is insufficient.
"""

    payload = {
        "model": MODEL,
        "messages": [{
            "role": "user",
            "content": prompt,
            "images": [encoded]
        }],
        "format": "json",
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0,
            "num_ctx": 4096
        }
    }

    response = httpx.post(
        OLLAMA,
        json=payload,
        timeout=180
    )
    response.raise_for_status()

    content = response.json()["message"]["content"]
    result = json.loads(content)

    relevant = result.get("relevant") is True

    try:
        confidence = float(result.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0.0

    approved = relevant and confidence >= 0.85

    return {
        "approved": approved,
        "confidence": confidence,
        "visible_subjects": result.get("visible_subjects", []),
        "reason": result.get("reason", "")
    }


if __name__ == "__main__":
    image = Path(
        "/opt/j3g-youtube-ai/assets/photos/hvac.jpg"
    )

    if not image.exists():
        raise SystemExit("TEST IMAGE NOT FOUND")

    tests = [
        ("Industrial HVAC air handling equipment", True),
        ("Toyota Corolla passenger automobile", False)
    ]

    for subject, expected in tests:
        print("\nREQUIRED SUBJECT:", subject)

        result = check_photo(image, subject)

        print("VISION RESULT:")
        print(json.dumps(result, indent=2))

        print(
            "TEST:",
            "PASSED" if result["approved"] == expected
            else "FAILED"
        )
