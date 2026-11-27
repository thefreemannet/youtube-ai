"""Save the TikTok app login and connect the administrator's personal account.

Nothing here uploads a video. The client secret and the tokens stay on the server.
"""

import html
import hmac
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests

from app.tiktok_uploader import CLIENT_FILE, TOKEN_FILE, _write_json

REDIRECT_URI = "https://youtube-ai.lab.j3gdigital.com/tiktok/callback"
AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
SCOPES = "user.info.basic,video.publish"
KEY_RE = re.compile(r"^[A-Za-z0-9]{10,80}$")
SECRET_RE = re.compile(r"^[A-Za-z0-9+/=_-]{16,200}$")
STATE_MAX_AGE = timedelta(minutes=15)


def _state_file():
    return CLIENT_FILE.with_name("tiktok_oauth_state.json")


def _read(path):
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _now():
    return datetime.now(timezone.utc)


def _parse_time(value):
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def connect_page(notice=""):
    """Return the private page where the administrator pastes the app credentials."""
    if TOKEN_FILE.is_file():
        form = "<p>TikTok is connected. Go back to the studio. Checking TikTok on Approve &amp; Publish can send the next video. After TikTok approves the production app, that post is public.</p>"
    else:
        note = "<p>" + html.escape(notice) + "</p>" if notice else ""
        form = note + """
<form method="post" action="/tiktok/connect" autocomplete="off">
  <label>Client key<br><input name="client_key" required maxlength="80" autocomplete="off" spellcheck="false"></label>
  <label>Client secret<br><input name="client_secret" type="password" required maxlength="200" autocomplete="off" spellcheck="false"></label>
  <button type="submit">Save and open TikTok</button>
</form>
"""
    return """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Connect TikTok</title>
<style>
body { font-family: Georgia, serif; max-width: 36rem; margin: 2rem auto; color: #1c1c1c; line-height: 1.4; }
label { display: block; margin: 1rem 0; }
input { width: 100%; box-sizing: border-box; padding: 0.45rem; }
button { background: #fe2c55; color: #fff; border: 0; padding: 0.6rem 1rem; cursor: pointer; }
</style></head><body>
<h1>Connect TikTok</h1>
<p>Paste the Client key and Client secret from J3G Social Publisher. They stay on this server. This does not submit the app for review and does not upload a video.</p>
<p>After you press the button, TikTok opens. Stay signed in to your personal TikTok account and press Allow.</p>
<p>If TikTok says this app is not available, add your TikTok username under Sandbox on the developer site, then open this page again.</p>
""" + form + "</body></html>"


def authorize_url(client_key, client_secret):
    """Store the app credentials and return TikTok's Allow page for this account."""
    key = str(client_key or "").strip()
    secret = str(client_secret or "").strip()
    if KEY_RE.fullmatch(key) is None or SECRET_RE.fullmatch(secret) is None:
        raise ValueError("The Client key or Client secret does not look like a TikTok credential")
    if TOKEN_FILE.is_file():
        raise ValueError("TikTok is already connected")
    _write_json(CLIENT_FILE, {
        "client_key": key,
        "client_secret": secret,
        "redirect_uri": REDIRECT_URI,
    })
    import secrets
    state = secrets.token_hex(16)
    _write_json(_state_file(), {
        "state": state,
        "created_utc": _now().isoformat(),
    })
    return AUTHORIZE_URL + "?" + urlencode({
        "client_key": key,
        "response_type": "code",
        "scope": SCOPES,
        "redirect_uri": REDIRECT_URI,
        "state": state,
        "disable_auto_auth": "1",
    })


def _public_failure(payload):
    code = ""
    if isinstance(payload, dict):
        code = str(payload.get("error") or "")
    if code in {"access_denied", "invalid_client", "invalid_grant", "invalid_request", "unauthorized_client"}:
        return "TikTok did not accept the login"
    return "TikTok did not accept the login"


def _exchange(body):
    try:
        response = requests.post(
            TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded", "Cache-Control": "no-cache"},
            data=body,
            timeout=30,
        )
        payload = response.json()
    except (requests.RequestException, ValueError):
        raise ValueError("TikTok did not accept the login")
    if response.status_code >= 400 or not isinstance(payload, dict) or not payload.get("access_token"):
        raise ValueError(_public_failure(payload))
    return payload


def _stored_token(payload):
    scope = str(payload.get("scope") or "")
    granted = {part.strip() for part in scope.split(",") if part.strip()}
    if "video.publish" not in granted:
        raise ValueError("TikTok did not grant posting")
    token = str(payload.get("access_token") or "").strip()
    refresh = str(payload.get("refresh_token") or "").strip()
    if not token or not refresh:
        raise ValueError("TikTok did not accept the login")
    try:
        expires_in = int(payload.get("expires_in") or 0)
        refresh_expires_in = int(payload.get("refresh_expires_in") or 0)
    except (TypeError, ValueError):
        raise ValueError("TikTok did not accept the login")
    if expires_in <= 0 or refresh_expires_in <= 0:
        raise ValueError("TikTok did not accept the login")
    return {
        "access_token": token,
        "refresh_token": refresh,
        "open_id": str(payload.get("open_id") or ""),
        "scope": scope,
        "expires_in": expires_in,
        "refresh_expires_in": refresh_expires_in,
        "token_type": "Bearer",
        "obtained_utc": _now().isoformat(),
    }


def finish_login(code, state):
    """Exchange TikTok's one-time code for a server-side token."""
    given = str(state or "")
    auth_code = str(code or "").strip()
    pending = _read(_state_file())
    expected = str(pending.get("state") or "")
    created = _parse_time(pending.get("created_utc"))
    if (
        not expected
        or len(given) != len(expected)
        or not hmac.compare_digest(given, expected)
        or created is None
        or _now() - created > STATE_MAX_AGE
        or not auth_code
        or len(auth_code) > 512
        or any(ch.isspace() for ch in auth_code)
    ):
        raise ValueError("TikTok did not accept the login")
    if TOKEN_FILE.is_file():
        raise ValueError("TikTok is already connected")
    client = _read(CLIENT_FILE)
    key = str(client.get("client_key") or "")
    secret = str(client.get("client_secret") or "")
    if KEY_RE.fullmatch(key) is None or SECRET_RE.fullmatch(secret) is None:
        raise ValueError("TikTok account is not connected")
    try:
        payload = _exchange({
            "client_key": key,
            "client_secret": secret,
            "code": auth_code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
        })
        saved = _stored_token(payload)
        _write_json(TOKEN_FILE, saved)
    finally:
        try:
            _state_file().unlink()
        except OSError:
            pass
    return saved


def refreshed_token(data):
    """Return a token that is still valid, refreshing it on the server when it is close to expiry."""
    if not isinstance(data, dict):
        raise ValueError("TikTok account is not connected")
    token = str(data.get("access_token") or "").strip()
    if not token:
        raise ValueError("TikTok account is not connected")
    obtained = _parse_time(data.get("obtained_utc"))
    try:
        expires_in = int(data.get("expires_in") or 0)
    except (TypeError, ValueError):
        expires_in = 0
    if obtained is None or expires_in <= 0:
        return data
    if obtained + timedelta(seconds=expires_in) > _now() + timedelta(minutes=10):
        return data
    client = _read(CLIENT_FILE)
    key = str(client.get("client_key") or "")
    secret = str(client.get("client_secret") or "")
    refresh = str(data.get("refresh_token") or "").strip()
    if KEY_RE.fullmatch(key) is None or SECRET_RE.fullmatch(secret) is None or not refresh:
        raise ValueError("TikTok account is not connected")
    payload = _exchange({
        "client_key": key,
        "client_secret": secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh,
    })
    saved = _stored_token(payload)
    _write_json(TOKEN_FILE, saved)
    return saved
