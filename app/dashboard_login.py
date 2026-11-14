"""Web login and logout for J3G YouTube AI."""

from html import escape
from urllib.parse import parse_qs

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.dashboard_auth import (
    authenticate,
    create_session,
    delete_session,
    session_user,
    SESSION_MAX_AGE,
)

from app.login_rate_limit import login_is_blocked, record_failure, clear_failures

router = APIRouter()
COOKIE_NAME = "j3g_session"


def login_page(error=""):
    message = (
        f'<p class="error">{escape(error)}</p>'
        if error else ""
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Login | J3G YouTube AI</title>
<style>
body {{
    margin:0;
    min-height:100vh;
    display:grid;
    place-items:center;
    background:#0c1424;
    color:#f1f5f9;
    font-family:Arial,sans-serif;
}}
.card {{
    background:#172337;
    border:1px solid #304158;
    padding:35px;
    border-radius:16px;
    width:min(360px,85vw);
}}
h1 {{color:#38bdf8;font-size:24px}}
label {{display:block;margin-top:18px}}
input {{
    box-sizing:border-box;
    width:100%;
    padding:12px;
    margin-top:7px;
    background:#0c1424;
    border:1px solid #40566c;
    color:white;
    border-radius:7px;
}}
button {{
    width:100%;
    margin-top:25px;
    padding:13px;
    background:#0284c7;
    color:white;
    border:0;
    border-radius:7px;
    cursor:pointer;
    font-weight:bold;
}}
.error {{color:#fda4af}}
.subtitle {{color:#94a3b8}}
</style>
</head>
<body>
<section class="card">
<h1>J3G YouTube AI</h1>
<p class="subtitle">Administrator Login</p>
{message}
<form method="post" action="/login">
<label>Username
<input name="username" autocomplete="username"
       maxlength="64" required>
</label>
<label>Password
<input name="password" type="password"
       autocomplete="current-password" required>
</label>
<button type="submit">Sign In</button>
</form>
</section>
</body>
</html>"""


@router.get("/login", response_class=HTMLResponse)
def login_screen(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if session_user(token):
        return RedirectResponse("/", status_code=303)

    response = HTMLResponse(login_page())
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/login")
async def login_submit(request: Request):
    origin = request.headers.get("origin")
    if origin:
        from urllib.parse import urlsplit
        parsed = urlsplit(origin)
        if parsed.netloc != request.headers.get("host"):
            return HTMLResponse(
                login_page("Invalid request origin."),
                status_code=403,
            )

    body = await request.body()
    if len(body) > 4096:
        return HTMLResponse(
            login_page("Invalid login request."),
            status_code=413,
        )

    values = parse_qs(body.decode("utf-8", errors="replace"))
    username = values.get("username", [""])[0]
    password = values.get("password", [""])[0]

    client_ip = request.client.host if request.client else "unknown"

    if login_is_blocked(username, client_ip):
        response = HTMLResponse(
            login_page("Too many login attempts. Try again later."),
            status_code=429,
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    if not authenticate(username, password):
        record_failure(username, client_ip)
        response = HTMLResponse(
            login_page("Invalid username or password."),
            status_code=401,
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    clear_failures(username, client_ip)
    token = create_session(username)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/logout")
def logout(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    delete_session(token)

    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE_NAME, path="/")
    response.headers["Cache-Control"] = "no-store"
    return response
