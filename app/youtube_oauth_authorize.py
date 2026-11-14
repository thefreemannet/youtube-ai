"""Authorize J3G YouTube publisher. No video uploads."""

import os
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

ROOT = Path("/opt/j3g-youtube-ai")
DIRECTORY = ROOT / "data/publisher/credentials"

CLIENT = DIRECTORY / "youtube_oauth_client.json"
TOKEN = DIRECTORY / "youtube_token.json"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload"
]

if TOKEN.exists():
    raise SystemExit(
        "OAuth token already exists. Refusing to overwrite."
    )

if not CLIENT.is_file():
    raise SystemExit("OAuth client credentials missing.")

flow = InstalledAppFlow.from_client_secrets_file(
    str(CLIENT),
    scopes=SCOPES
)

print("J3G YOUTUBE OAUTH")
print("Open the authorization URL below in Windows Chrome.")
print("SSH tunnel must remain connected.")
print("No video will be uploaded.", flush=True)

credentials = flow.run_local_server(
    host="127.0.0.1",
    port=8767,
    open_browser=False,
    access_type="offline",
    prompt="consent",
    success_message=(
        "J3G YouTube authorization received. "
        "You may close this browser tab."
    )
)

if not credentials.refresh_token:
    raise RuntimeError("No refresh token received.")

fd = os.open(
    TOKEN,
    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
    0o600
)

with os.fdopen(fd, "w", encoding="utf-8") as file:
    file.write(credentials.to_json())

print("GOOGLE OAUTH: AUTHORIZED")
print("TOKEN: SAVED SECURELY")
print("YOUTUBE UPLOADING: STILL DISABLED")
