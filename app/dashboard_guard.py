"""Authentication protection for J3G dashboard routes."""

from urllib.parse import urlsplit

from fastapi.responses import JSONResponse, RedirectResponse

from app.dashboard_auth import account_status, delete_session, is_admin, note_seen, session_user
from app.dashboard_login import COOKIE_NAME


def _accounts_path(path):
    return path == "/accounts" or path.startswith("/accounts/")


def _api_path(path):
    return path.startswith("/api/") or path.startswith("/videos/")


async def dashboard_guard(request, call_next):
    path = request.url.path

    if path in ("/login", "/register", "/api/health"):
        return await call_next(request)

    token = request.cookies.get(COOKIE_NAME)
    username = session_user(token)

    if username is None:
        if _api_path(path):
            return JSONResponse(
                {"detail": "Authentication required"},
                status_code=401,
            )
        return RedirectResponse("/login", status_code=303)

    status = account_status(username)
    if status in {"rejected", "missing"}:
        delete_session(token)
        if _api_path(path):
            return JSONResponse(
                {"detail": "This account was not approved"},
                status_code=403,
            )
        response = RedirectResponse("/login?rejected=1", status_code=303)
        response.delete_cookie(COOKIE_NAME, path="/")
        return response

    if status == "pending" and not (path == "/waiting" or path == "/logout"):
        if _api_path(path):
            return JSONResponse(
                {"detail": "Account is waiting for approval"},
                status_code=403,
            )
        return RedirectResponse("/waiting", status_code=303)

    if _accounts_path(path) and not is_admin(username):
        if request.method not in ("GET", "HEAD"):
            return JSONResponse({"detail": "Only the administrator can do that"}, status_code=403)
        return RedirectResponse("/", status_code=303)

    if status == "approved":
        note_seen(username)

    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin", "")
        host = request.headers.get("host", "")
        parsed = urlsplit(origin)
        local_host = host.split(":")[0].lower() in {"127.0.0.1", "localhost"}
        same_host = parsed.netloc.lower() == host.lower()
        if local_host:
            allowed = same_host and parsed.scheme in {"http", "https"}
        else:
            allowed = same_host and parsed.scheme == "https"
        if not allowed:
            return JSONResponse(
                {"detail": "Invalid request origin"},
                status_code=403,
            )

    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
