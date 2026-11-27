"""Persistent cartoon characters for every lesson.

A character is a folder under assets/characters. The reference image is reused
across scenes and videos. Text alone is not treated as enough to keep the
same person.
"""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.environ.get("J3G_ROOT", Path(__file__).resolve().parents[1]))
CHARACTERS = ROOT / "assets" / "characters"
ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{1,39}")


def character_id_from_config():
    path = ROOT / "visual_config.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "hvac-tech"
    chosen = str(raw.get("character_id") or "hvac-tech").strip()
    if not ID_RE.fullmatch(chosen):
        return "hvac-tech"
    return chosen


def character_dir(character_id):
    if not ID_RE.fullmatch(character_id or ""):
        raise ValueError("Invalid character id")
    folder = CHARACTERS / character_id
    if not folder.is_dir() or not (folder / "character.json").is_file():
        raise FileNotFoundError(f"Character not found: {character_id}")
    return folder


def load_character(character_id=None):
    character_id = character_id or character_id_from_config()
    folder = character_dir(character_id)
    data = json.loads((folder / "character.json").read_text(encoding="utf-8"))
    if data.get("id") != character_id:
        raise ValueError("Character file id does not match its folder")
    reference = folder / str(data.get("reference_image") or "reference.png")
    data["reference_path"] = str(reference) if reference.is_file() else None
    return data


def reference_bytes(character):
    path = character.get("reference_path")
    if not path:
        return None
    file = Path(path)
    if not file.is_file():
        return None
    return file.read_bytes()


def expression_for(caption, character):
    allowed = character.get("expressions") or ["neutral"]
    text = caption.casefold()
    if "pointing" in allowed and any(word in text for word in ("point", "schedule", "show")):
        return "pointing"
    if "concerned" in allowed and any(word in text for word in ("freeze", "cold", "wrong", "problem", "concern")):
        return "concerned"
    if "explaining" in allowed and any(word in text for word in ("open", "warm", "enter", "adjust")):
        return "explaining"
    return "neutral" if "neutral" in allowed else allowed[0]


def prompt_for(character, caption):
    clothing = character.get("clothing") or {}
    clothes = ", ".join(str(item) for item in clothing.values())
    expression = expression_for(caption, character)
    return (
        str(character.get("style") or "")
        + " The same character in every scene: "
        + str(character.get("visual_description") or "")
        + " Clothing stays exactly: "
        + clothes
        + f". Expression: {expression}, without changing the face, hair, or clothes."
        + " Do not draw any words, letters, numbers, captions, or logos."
        + " Vertical 9:16. Place the full character in the upper part of the frame and leave the area under the boots empty."
        + " Scene action, shown literally with simple props: "
        + caption
    )


def record_asset(character_id, job_id, scene_number, slide_path):
    folder = character_dir(character_id)
    history = folder / "history.jsonl"
    entry = {
        "utc": datetime.now(timezone.utc).isoformat(),
        "job_id": job_id,
        "scene": scene_number,
        "slide": str(slide_path),
    }
    with history.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
