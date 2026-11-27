"""Confirm an Instagram media object is the Reel that was just published.

This checks the response Instagram returns. It does not upload anything.
"""

from urllib.parse import urlsplit


def safe_permalink(url):
    parsed = urlsplit(str(url or "").strip())
    if parsed.scheme != "https" or parsed.hostname not in ("www.instagram.com", "instagram.com"):
        return ""
    if parsed.username or parsed.password:
        return ""
    return str(url).strip()


def reel_confirmation(media_id, payload):
    """Return the confirmed Reel, or raise if this object is not that Reel."""
    if not isinstance(payload, dict):
        raise RuntimeError("Instagram did not return the Reel")
    expected = str(media_id)
    found = str(payload.get("id") or "")
    if not expected.isdecimal() or found != expected:
        raise RuntimeError("Instagram Reel id did not match the published video")
    if str(payload.get("media_type") or "") != "VIDEO":
        raise RuntimeError("Instagram did not list this upload as a video")
    if str(payload.get("media_product_type") or "") != "REELS":
        raise RuntimeError("Instagram did not list this upload as a Reel")
    permalink = safe_permalink(payload.get("permalink"))
    if not permalink:
        raise RuntimeError("Instagram did not return a Reel link")
    return {
        "id": expected,
        "media_type": "VIDEO",
        "media_product_type": "REELS",
        "permalink": permalink,
    }
