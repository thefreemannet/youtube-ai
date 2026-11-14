"""J3G Visual Asset Manager — reusable, verified image catalog.

Catalog registration does not grant permission to use an image.
Every scene requires fresh visual relevance validation.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
LIBRARY = ROOT / "data" / "visual_assets"
DB = LIBRARY / "catalog.sqlite3"

ALLOWED_TYPES = {"photograph", "ai_illustration", "diagram"}

STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that",
    "image", "photo", "scene", "video", "system", "equipment",
    "commercial", "technical", "hvac", "illustration"
}


def connect():
    if not DB.is_file():
        raise RuntimeError("Visual asset database is missing")

    con = sqlite3.connect(DB, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def file_hash(path):
    digest = hashlib.sha256()

    with Path(path).open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)

    return digest.hexdigest()


def keywords(text):
    return {
        word for word in re.findall(
            r"[a-z0-9]+", str(text).lower()
        )
        if len(word) >= 3 and word not in STOPWORDS
    }


def register_asset(
    path,
    asset_type,
    source_type,
    description,
    subjects,
    source_url=None,
    creator=None,
    license_name=None,
    license_url=None,
    attribution=None,
    generation_model=None,
):
    """Register an image with all approval statuses pending."""

    if asset_type not in ALLOWED_TYPES:
        raise ValueError("Unsupported asset type")

    path = Path(path).resolve()
    library_root = LIBRARY.resolve()

    if not path.is_relative_to(library_root):
        raise ValueError("Image must be inside the visual asset library")

    if path.parent.name not in {
        "candidates", "verified", "generated"
    }:
        raise ValueError("Unsupported asset storage directory")

    if not path.is_file():
        raise FileNotFoundError(path)

    if not isinstance(subjects, list) or not all(
        isinstance(item, str) for item in subjects
    ):
        raise ValueError("Subjects must be a list of strings")

    if not description.strip():
        raise ValueError("Image description is required")

    with Image.open(path) as image:
        if image.format not in {"JPEG", "PNG", "WEBP"}:
            raise ValueError("Unsupported image format")

        width, height = image.size
        image.verify()

    sha = file_hash(path)

    with connect() as con:
        existing = con.execute(
            "SELECT id FROM assets WHERE sha256 = ?",
            (sha,)
        ).fetchone()

        if existing:
            return int(existing["id"])

        cursor = con.execute(
            """
            INSERT INTO assets (
                sha256, file_path, asset_type, source_type,
                source_url, creator, license_name, license_url,
                attribution, generation_model, width, height,
                description, subjects_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sha, str(path), asset_type, source_type,
                source_url, creator, license_name, license_url,
                attribution, generation_model, width, height,
                description, json.dumps(subjects)
            )
        )

        return cursor.lastrowid


def find_candidates(scene_subject, job_id=None, limit=10):
    """Find potentially reusable images, never auto-approve them."""

    wanted = keywords(scene_subject)

    if not wanted:
        return []

    with connect() as con:
        rows = con.execute(
            """
            SELECT *
            FROM assets AS a
            WHERE a.rights_status = 'cleared'
              AND a.visual_status = 'pass'
              AND a.technical_status = 'pass'
              AND a.human_status != 'rejected'
              AND NOT EXISTS (
                  SELECT 1
                  FROM scene_assignments AS s
                  WHERE s.asset_id = a.id
                    AND s.job_id = ?
              )
            """,
            (job_id or "",)
        ).fetchall()

    ranked = []

    for row in rows:
        path = Path(row["file_path"])

        if not path.is_file():
            continue

        if file_hash(path) != row["sha256"]:
            continue

        searchable = (
            row["description"] + " " +
            " ".join(json.loads(row["subjects_json"]))
        )

        matching = wanted & keywords(searchable)

        if not matching:
            continue

        ranked.append({
            "asset_id": row["id"],
            "path": str(path),
            "asset_type": row["asset_type"],
            "matching_terms": sorted(matching),
            "score": len(matching),
            "requires_scene_validation": True
        })

    ranked.sort(
        key=lambda item: item["score"],
        reverse=True
    )

    return ranked[:limit]


def catalog_status():
    with connect() as con:
        total = con.execute(
            "SELECT COUNT(*) FROM assets"
        ).fetchone()[0]

        eligible = con.execute(
            """
            SELECT COUNT(*) FROM assets
            WHERE rights_status = 'cleared'
              AND visual_status = 'pass'
              AND technical_status = 'pass'
              AND human_status != 'rejected'
            """
        ).fetchone()[0]

    return {
        "total_assets": total,
        "reuse_candidates": eligible
    }


if __name__ == "__main__":
    print("=== J3G VISUAL ASSET MANAGER ===")
    print(json.dumps(catalog_status(), indent=2))

    print("AHU search:",
          len(find_candidates("AHU cooling coil")))

    print("VAV search:",
          len(find_candidates("VAV damper actuator")))

    print("ASSET MANAGER MODULE: READY")
    print("ACTIVE PRODUCTION ENGINE: UNCHANGED")
