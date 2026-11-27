"""Read one operator picture and keep a JPEG the video can be written about."""

import base64
import json
from email import message_from_bytes
from email.policy import default
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image, ImageOps

OLLAMA = "http://192.168.120.107:11434/api/chat"
MODEL = "qwen3.5:9b"
MAX_BYTES = 8 * 1024 * 1024


def form_picture(payload, content_type):
    """Read the create-video form without adding a multipart library."""
    header = ("Content-Type: " + content_type + "\r\nMIME-Version: 1.0\r\n\r\n").encode("utf-8")
    message = message_from_bytes(header + payload, policy=default)
    if not message.is_multipart():
        raise ValueError("Upload the picture with the video form")
    fields = {}
    picture = b""
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        data = part.get_payload(decode=True) or b""
        if name == "picture":
            picture = data
        else:
            fields[name] = data.decode("utf-8", "replace")
    return fields, picture


def save_source_picture(data, dest):
    """Store a JPEG copy. Reject anything that is not a normal picture."""
    if not isinstance(data, (bytes, bytearray)) or not data or len(data) > MAX_BYTES:
        raise ValueError("Use a JPEG, PNG, or WebP picture under 8 MB")
    try:
        with Image.open(BytesIO(data)) as source:
            if source.format not in {"JPEG", "PNG", "WEBP"}:
                raise ValueError("Use a JPEG, PNG, or WebP picture")
            image = ImageOps.exif_transpose(source).convert("RGB")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("The picture could not be read") from exc
    if image.width < 32 or image.height < 32:
        raise ValueError("The picture is too small")
    image.thumbnail((1600, 1600))
    dest.parent.mkdir(parents=True, exist_ok=True)
    image.save(dest, format="JPEG", quality=85)


def describe_picture(path):
    """Return the visible facts in the picture. This does not invent a different subject."""
    path = Path(path)
    with Image.open(path) as original:
        image = ImageOps.exif_transpose(original).convert("RGB")
        image.thumbnail((1024, 1024))
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=85)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    payload = {
        "model": MODEL,
        "messages": [{
            "role": "user",
            "content": (
                "Look at the picture. Describe only what is visible, in 80 to 140 words. "
                "Do not invent labels, measurements, or causes that the picture does not show. "
                "Return JSON with one field named description."
            ),
            "images": [encoded],
        }],
        "format": "json",
        "stream": False,
        "think": False,
        "options": {"temperature": 0, "num_ctx": 4096},
    }
    response = httpx.post(OLLAMA, json=payload, timeout=180)
    response.raise_for_status()
    content = response.json()["message"]["content"]
    result = json.loads(content)
    description = " ".join(str(result.get("description") or "").split())
    if len(description) < 40:
        raise RuntimeError("The picture could not be described")
    return description[:1200]
