"""Web login and logout for J3G YouTube AI."""

import os
from html import escape
from urllib.parse import parse_qs

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.dashboard_auth import (
    account_status,
    check_login,
    create_session,
    delete_session,
    record_login,
    register_account,
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
.subtitle, .note {{color:#94a3b8}}
a {{color:#7dd3fc}}
</style>
</head>
<body>
<section class="card">
<h1>J3G YouTube AI</h1>
<p class="subtitle">Sign in</p>
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
<p class="note">Need an account? <a href="/register">Create an account</a></p>
</section>
</body>
</html>"""


def _cookie_secure():
    return os.environ.get("J3G_COOKIE_SECURE", "1") != "0"


def _same_origin(request):
    origin = request.headers.get("origin")
    if not origin:
        return True
    from urllib.parse import urlsplit
    parsed = urlsplit(origin)
    return parsed.netloc == request.headers.get("host")


def _redirect_for_status(status):
    if status == "pending":
        return RedirectResponse("/waiting", status_code=303)
    if status == "approved":
        return RedirectResponse("/", status_code=303)
    return None


@router.get("/login", response_class=HTMLResponse)
def login_screen(request: Request):
    username = session_user(request.cookies.get(COOKIE_NAME))
    if username:
        redirect = _redirect_for_status(account_status(username))
        if redirect is not None:
            return redirect

    error = ""
    if request.query_params.get("rejected") == "1":
        error = "This account was not approved."
    response = HTMLResponse(login_page(error))
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/login")
async def login_submit(request: Request):
    if not _same_origin(request):
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

    result = check_login(username, password)
    if result == "invalid":
        record_failure(username, client_ip)
        response = HTMLResponse(
            login_page("Invalid username or password."),
            status_code=401,
        )
        response.headers["Cache-Control"] = "no-store"
        return response
    if result == "rejected":
        response = HTMLResponse(
            login_page("This account was not approved."),
            status_code=403,
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    clear_failures(username, client_ip)
    record_login(username)
    token = create_session(username)
    destination = "/waiting" if result == "pending" else "/"
    response = RedirectResponse(destination, status_code=303)
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=_cookie_secure(),
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


def account_form(title, subtitle, error="", values=None):
    values = values or {}
    message = f'<p class="error">{escape(error)}</p>' if error else ""
    return login_page("").replace(
        "<h1>J3G YouTube AI</h1>\n<p class=\"subtitle\">Sign in</p>\n",
        f"<h1>J3G YouTube AI</h1>\n<p class=\"subtitle\">{escape(subtitle)}</p>\n{message}",
    ).replace(
        """<form method="post" action="/login">
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
<p class="note">Need an account? <a href="/register">Create an account</a></p>""",
        f"""<form method="post" action="/register">
<label>Name
<input name="name" autocomplete="name" maxlength="80" required value="{escape(values.get('name', ''))}">
</label>
<label>Username
<input name="username" autocomplete="username" maxlength="32" required value="{escape(values.get('username', ''))}">
</label>
<label>Email
<input name="email" type="email" autocomplete="email" maxlength="120" required value="{escape(values.get('email', ''))}">
</label>
<label>Password
<input name="password" type="password" autocomplete="new-password" minlength="8" required>
</label>
<label>Confirm password
<input name="confirm" type="password" autocomplete="new-password" minlength="8" required>
</label>
<button type="submit">Create account</button>
</form>
<p class="note">Already registered? <a href="/login">Sign in</a></p>""",
    ).replace("<title>Login | J3G YouTube AI</title>", f"<title>{escape(title)} | J3G YouTube AI</title>")


def waiting_page():
    page = login_page("").replace(
        "<p class=\"subtitle\">Sign in</p>",
        "<p class=\"subtitle\">Waiting for approval</p>",
    ).replace(
        """<form method="post" action="/login">
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
<p class="note">Need an account? <a href="/register">Create an account</a></p>""",
        """<p>Your account was created. It stays closed until <strong>thefreemannet</strong> approves it.</p>
<p class="note">You can sign in again after it is approved.</p>
<form method="post" action="/logout"><button type="submit">Sign out</button></form>""",
    )
    return page.replace("<title>Login | J3G YouTube AI</title>", "<title>Waiting for approval | J3G YouTube AI</title>")


@router.get("/register", response_class=HTMLResponse)
def register_screen(request: Request):
    username = session_user(request.cookies.get(COOKIE_NAME))
    if username:
        redirect = _redirect_for_status(account_status(username))
        if redirect is not None:
            return redirect
    response = HTMLResponse(account_form(
        "Create account",
        "The administrator approves new accounts before they can sign in to the studio.",
    ))
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/register")
async def register_submit(request: Request):
    if not _same_origin(request):
        return HTMLResponse(
            account_form("Create account", "Create an account", "Invalid request origin."),
            status_code=403,
        )
    body = await request.body()
    if len(body) > 4096:
        return HTMLResponse(
            account_form("Create account", "Create an account", "Invalid registration request."),
            status_code=413,
        )
    values = parse_qs(body.decode("utf-8", errors="replace"))
    entered = {
        "name": values.get("name", [""])[0],
        "username": values.get("username", [""])[0],
        "email": values.get("email", [""])[0],
    }
    password = values.get("password", [""])[0]
    confirm = values.get("confirm", [""])[0]
    client_ip = request.client.host if request.client else "unknown"
    if login_is_blocked("register", client_ip):
        response = HTMLResponse(
            account_form("Create account", "Create an account", "Too many attempts. Try again later.", entered),
            status_code=429,
        )
        response.headers["Cache-Control"] = "no-store"
        return response
    if password != confirm:
        response = HTMLResponse(
            account_form("Create account", "Create an account", "Passwords do not match.", entered),
            status_code=400,
        )
        response.headers["Cache-Control"] = "no-store"
        return response
    try:
        account = register_account(entered["name"], entered["username"], entered["email"], password)
    except ValueError as exc:
        record_failure("register", client_ip)
        response = HTMLResponse(
            account_form("Create account", "Create an account", str(exc), entered),
            status_code=400,
        )
        response.headers["Cache-Control"] = "no-store"
        return response
    token = create_session(account)
    response = RedirectResponse("/waiting", status_code=303)
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/waiting", response_class=HTMLResponse)
def waiting_screen(request: Request):
    username = session_user(request.cookies.get(COOKIE_NAME))
    status = account_status(username) if username else "missing"
    if status == "approved":
        return RedirectResponse("/", status_code=303)
    if status != "pending":
        return RedirectResponse("/login", status_code=303)
    response = HTMLResponse(waiting_page())
    response.headers["Cache-Control"] = "no-store"
    return response
