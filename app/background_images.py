"""Offline photographic backgrounds for J3G slides.

Rendering reads only local JPEG or PNG files that already have usage metadata.
It never contacts Wikimedia Commons or any other image service. A missing,
unlicensed, or unreadable image leaves that scene on the solid dark background.
"""

import json
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image, ImageFilter, ImageOps

CANVAS = (720, 1280)
DARK = (12, 20, 36)  # #0c1424, the existing slide base
MIN_OPACITY = 0.05
MAX_OPACITY = 0.10
DEFAULT_OPACITY = 0.08
MAX_IMAGE_BYTES = 25_000_000
ALLOWED_FORMATS = {"JPEG", "PNG"}
LICENSES = {"CC0", "CC0 1.0", "CC BY 2.0", "CC BY 2.5", "CC BY 3.0", "CC BY 4.0"}
BACKGROUND_FIELDS = (
    "background_image",
    "background_opacity",
    "background_source",
    "background_license",
    "background_attribution",
)


def load_background_config(root):
    """Read visual_config.json. Invalid values fall back to photo mode at 8%."""
    mode = "photo"
    opacity = DEFAULT_OPACITY
    blur = 0.0
    path = Path(root) / "visual_config.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        background = raw.get("background") if isinstance(raw, dict) else {}
        if not isinstance(background, dict):
            background = {}
        requested = str(background.get("mode") or "photo").strip().lower()
        if requested in {"solid", "photo"}:
            mode = requested
        opacity = _opacity_or_default(background.get("opacity", DEFAULT_OPACITY))
        blur = float(background.get("blur_radius") or 0)
        if blur < 0 or blur > 8:
            blur = 0.0
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        mode, opacity, blur = "photo", DEFAULT_OPACITY, 0.0
    if mode == "solid":
        opacity = 0.0
    return {"mode": mode, "opacity": opacity, "blur": blur}


def _opacity_or_default(value):
    try:
        opacity = float(value)
    except (TypeError, ValueError):
        return DEFAULT_OPACITY
    if MIN_OPACITY <= opacity <= MAX_OPACITY:
        return opacity
    return DEFAULT_OPACITY


def scene_opacity(scene, default):
    if isinstance(scene, dict) and "background_opacity" in scene:
        try:
            opacity = float(scene["background_opacity"])
        except (TypeError, ValueError):
            return _opacity_or_default(default)
        if MIN_OPACITY <= opacity <= MAX_OPACITY:
            return opacity
    return _opacity_or_default(default)


def expected_background_pixel(photo_rgb, opacity, dark=DARK):
    """8-bit form of dark * (1 - alpha) + photograph * alpha.

    Pillow quantizes alpha to 0-255 and uses integer division. The result stays
    within one level of the real-valued formula.
    """
    alpha = int(round(float(opacity) * 255))
    return tuple(
        (base * (255 - alpha) + sample * alpha) // 255
        for base, sample in zip(dark, photo_rgb)
    )


def decode_image(path):
    """Return a loaded RGB image or raise ValueError for anything unusable."""
    file = Path(path)
    if file.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
        raise ValueError("Unsupported image type")
    size = file.stat().st_size
    if size < 32 or size > MAX_IMAGE_BYTES:
        raise ValueError("Image file is empty, tiny, or too large")
    data = file.read_bytes()
    if data.startswith(b"%PDF"):
        raise ValueError("PDF files cannot be used as backgrounds")
    try:
        with Image.open(file) as probe:
            if probe.format not in ALLOWED_FORMATS:
                raise ValueError("Unsupported image format")
            probe.verify()
        with Image.open(file) as source:
            if source.format not in ALLOWED_FORMATS:
                raise ValueError("Unsupported image format")
            image = ImageOps.exif_transpose(source)
            image.load()
            return image.convert("RGB")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Image could not be decoded") from exc


def cover_crop(image, size=CANVAS):
    """Fill the vertical frame without stretching. Small files are rejected."""
    if image.width < 1 or image.height < 1:
        raise ValueError("Image has no pixels")
    if min(image.width, image.height) < 720:
        raise ValueError("Image resolution too low")
    return ImageOps.fit(
        image,
        size,
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )


def blend_background(photograph, opacity, blur=0.0):
    """Composite a photograph over the dark slide at the given opacity.

    alpha is the photograph's contribution. This is not a black overlay on a
    full-strength photograph.
    """
    alpha = float(opacity)
    if not (MIN_OPACITY <= alpha <= MAX_OPACITY):
        raise ValueError("Background opacity must stay between 5% and 10%")
    if not isinstance(photograph, Image.Image):
        photograph = decode_image(photograph)
    fitted = cover_crop(photograph.convert("RGB"))
    if blur and float(blur) > 0:
        fitted = fitted.filter(ImageFilter.GaussianBlur(float(blur)))
    base = Image.new("RGB", CANVAS, DARK)
    return Image.blend(base, fitted, alpha)


def _source_allowed(source):
    if not isinstance(source, str):
        return False
    if source.startswith("local:"):
        name = source[6:]
        return bool(name) and all(token not in name for token in ("/", "\\", ".."))
    parsed = urlsplit(source)
    return (
        parsed.scheme == "https"
        and parsed.hostname == "commons.wikimedia.org"
        and not parsed.username
        and not parsed.password
    )


def license_errors(metadata):
    """Return reasons an image must not be used. An empty list means it may."""
    if not isinstance(metadata, dict):
        return ["Image license metadata is missing"]
    errors = []
    if metadata.get("approved_for_use") is not True:
        errors.append("Image is not approved for use")
    license_name = str(metadata.get("license") or "")
    if license_name not in LICENSES:
        errors.append("Unrecognized or unsupported license")
    if not _source_allowed(str(metadata.get("source") or "")):
        errors.append("Image source is missing or not an allowed origin")
    attribution = str(metadata.get("attribution") or "").strip()
    if not attribution:
        errors.append("Attribution is missing")
    if license_name.startswith("CC BY"):
        if not str(metadata.get("author") or "").strip():
            errors.append("Author credit is missing")
        license_url = str(metadata.get("license_url") or "")
        parsed = urlsplit(license_url)
        if parsed.scheme != "https" or parsed.hostname not in {
            "creativecommons.org",
            "www.creativecommons.org",
        }:
            errors.append("License link is missing or invalid")
    return errors


def _contained(path, roots):
    resolved = Path(path).resolve(strict=True)
    allowed = [Path(root).resolve() for root in roots]
    if not any(resolved.is_relative_to(root) for root in allowed):
        raise ValueError("Image is outside the approved background directories")
    return resolved


def validate_cached_image(path, roots):
    resolved = _contained(path, roots)
    image = decode_image(resolved)
    cover_crop(image)
    sidecar = resolved.with_suffix(".json")
    if not sidecar.is_file() or not sidecar.resolve().is_relative_to(resolved.parent):
        raise ValueError("Image license metadata is missing")
    try:
        metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Image license metadata is unreadable") from exc
    errors = license_errors(metadata)
    if errors:
        raise ValueError("; ".join(errors))
    return image, metadata, resolved


def _scene_text(scene):
    return " ".join(
        str(scene.get(key) or "")
        for key in ("heading", "body", "background_query")
    ).casefold()


_EQUIPMENT = (
    "air handler", "air handling", "duct", "fan", "motor", "thermostat",
    "ventilation", "damper", "compressor", "chiller", "pump", "hvac",
    "variable frequency", "drive", "panel", "coil", "filter", "electrical",
)
_UNRELATED_TITLE = ("sculpture", "racing", "formule", "toyota", "corolla", "extravalan")


def _has_picture_detail(path):
    """Reject flat color fields. A photograph has variation across the frame."""
    sample = decode_image(path).resize((32, 32))
    colors = sample.getcolors(maxcolors=32 * 32)
    return bool(colors and len(colors) >= 12)


def _library_entries(directories):
    entries = []
    for directory in directories:
        folder = Path(directory)
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            if path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
                continue
            if "preview" in path.stem.casefold():
                continue
            try:
                _image, metadata, resolved = validate_cached_image(path, [folder])
                if not _has_picture_detail(resolved):
                    continue
            except (OSError, ValueError):
                continue
            entries.append({
                "path": resolved,
                "metadata": metadata,
                "subjects": metadata.get("subjects") or [],
            })
    return entries


def _entry_focus(entry):
    metadata = entry.get("metadata") or {}
    return " ".join([
        str(metadata.get("title") or ""),
        str(metadata.get("search_query") or ""),
        " ".join(str(subject) for subject in entry.get("subjects") or []),
    ]).casefold()


def _video_terms(topic, scenes):
    blob = " ".join([str(topic or "")] + [_scene_text(scene) for scene in scenes]).casefold()
    cleaned = "".join(char if char.isalnum() or char.isspace() else " " for char in blob)
    terms = {word for word in cleaned.split() if len(word) >= 4}
    for hint in _EQUIPMENT:
        if hint in blob:
            terms.add(hint)
    return terms


def _relevance(topic, scenes, entry):
    title = str((entry.get("metadata") or {}).get("title") or "").casefold()
    if any(blocked in title for blocked in _UNRELATED_TITLE):
        return 0
    focus = _entry_focus(entry)
    score = 0
    for term in _video_terms(topic, scenes):
        if term and term in focus:
            score += 3 if " " in term else 1
    return score


def assign_scenes(scenes, entries, topic=""):
    """Use one topic-related photograph for the whole video."""
    best = None
    best_score = 0
    for entry in entries:
        score = _relevance(topic, scenes, entry)
        if score > best_score:
            best, best_score = entry, score
    if best is None:
        return {}
    return {index: best for index in range(len(scenes))}


def _write_scene(scene, source, metadata, opacity):
    dest_dir = Path(scene["_background_dir"])
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"shared{Path(source).suffix.lower()}"
    if Path(source).resolve() != dest.resolve():
        dest.write_bytes(Path(source).read_bytes())
    sidecar = dest.with_suffix(".json")
    sidecar.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    scene["background_image"] = str(dest)
    scene["background_opacity"] = opacity
    scene["background_source"] = metadata.get("source")
    scene["background_license"] = metadata.get("license")
    scene["background_attribution"] = metadata.get("attribution")
    scene.pop("_background_dir", None)
    return str(dest)


def prepare_plan_backgrounds(plan, folder, root):
    """Attach cached licensed images. Never downloads and never raises."""
    cfg = load_background_config(root)
    plan["background_mode"] = cfg["mode"]
    plan["background_opacity"] = cfg["opacity"]
    plan["background_blur"] = cfg["blur"]
    scenes = plan.get("scenes") if isinstance(plan.get("scenes"), list) else []
    if cfg["mode"] != "photo":
        for scene in scenes:
            for field in BACKGROUND_FIELDS:
                scene.pop(field, None)
        return []
    folder = Path(folder)
    roots = [folder, folder / "backgrounds", folder / "background_library"]
    library_dirs = [
        folder / "background_library",
        Path(root) / "assets" / "backgrounds",
        Path(root) / "assets" / "photos",
    ]
    entries = _library_entries(library_dirs)
    needs = []
    for scene in scenes:
        existing = scene.get("background_image")
        if not existing:
            needs.append(scene)
            continue
        try:
            _image, metadata, resolved = validate_cached_image(existing, roots)
        except (OSError, ValueError):
            for field in BACKGROUND_FIELDS:
                scene.pop(field, None)
            needs.append(scene)
            continue
        opacity = scene_opacity(scene, cfg["opacity"])
        scene["background_image"] = str(resolved)
        scene["background_opacity"] = opacity
        scene["background_source"] = metadata.get("source")
        scene["background_license"] = metadata.get("license")
        scene["background_attribution"] = metadata.get("attribution")
    chosen = assign_scenes(needs, entries, topic=plan.get("topic") or "")
    for scene, pick in (
        (needs[index], chosen[index])
        for index in range(len(needs))
        if index in chosen
    ):
        scene["_background_dir"] = str(folder / "backgrounds")
        try:
            _write_scene(scene, pick["path"], pick["metadata"], scene_opacity(scene, cfg["opacity"]))
        except (OSError, ValueError):
            scene.pop("_background_dir", None)
            for field in BACKGROUND_FIELDS:
                scene.pop(field, None)
    for scene in scenes:
        scene.pop("_background_dir", None)
    return [scene.get("background_image") for scene in scenes if scene.get("background_image")]


def compose_scene_background(scene, plan, roots):
    """Return the RGB canvas for one scene and the image path actually used."""
    base = Image.new("RGB", CANVAS, DARK)
    if plan.get("background_mode") != "photo" or not scene.get("background_image"):
        return base, None
    try:
        image, _metadata, resolved = validate_cached_image(scene["background_image"], roots)
        opacity = scene_opacity(scene, plan.get("background_opacity", DEFAULT_OPACITY))
        blur = float(plan.get("background_blur") or 0)
        return blend_background(image, opacity, blur=blur), str(resolved)
    except (OSError, ValueError):
        for field in BACKGROUND_FIELDS:
            scene.pop(field, None)
        return base, None
