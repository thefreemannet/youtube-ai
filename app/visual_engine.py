import json
from pathlib import Path
from PIL import Image, ImageOps

try:
    from app.background_images import blend_background
except ImportError:  # scripts on the server import modules from app/
    from background_images import blend_background

ROOT = Path("/opt/j3g-youtube-ai")
CONFIG = ROOT / "visual_config.json"


def load_config():
    with CONFIG.open(encoding="utf-8") as f:
        return json.load(f)


def create_background(photo_path):
    cfg = load_config()

    if list(cfg["layout"]["resolution"]) != [720, 1280]:
        raise ValueError("Slide resolution must stay 720x1280")
    bgcfg = cfg["background"]

    opacity = float(bgcfg["opacity"])
    blur = float(bgcfg["blur_radius"])

    if not 0.05 <= opacity <= 0.10:
        raise ValueError("Background opacity must stay between 5% and 10%")

    photo_path = Path(photo_path)

    if not photo_path.is_file():
        raise FileNotFoundError(photo_path)

    # Each photograph requires approved usage metadata.
    metadata_path = photo_path.with_suffix(".json")

    if bgcfg["licensed_images_only"]:
        if not metadata_path.is_file():
            raise ValueError("Image licensing metadata missing")

        metadata = json.loads(metadata_path.read_text())

        if not metadata.get("approved_for_use"):
            raise ValueError("Image not approved for use")

        if not metadata.get("license") or not metadata.get("source"):
            raise ValueError("Incomplete image license metadata")

    with Image.open(photo_path) as source:
        source = ImageOps.exif_transpose(source)
        source = source.convert("RGB")

        if source.width * source.height < 1920 * 1080:
            raise ValueError("Image resolution too low")
        photograph = source.convert("RGB")

    # Shared formula: dark * (1 - alpha) + photograph * alpha.
    return blend_background(photograph, opacity, blur=blur)


if __name__ == "__main__":
    cfg = load_config()

    print("GLOBAL PHOTO ENGINE READY")
    print("Resolution:", cfg["layout"]["resolution"])
    print("Opacity:", cfg["background"]["opacity"])
    print("Photography required:", cfg["background"]["type"])
    print("Licensed images only:", cfg["background"]["licensed_images_only"])
