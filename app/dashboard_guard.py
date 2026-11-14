"""Authentication protection for J3G dashboard routes."""

from urllib.parse import urlsplit

from fastapi.responses import JSONResponse, RedirectResponse

from app.dashboard_auth import session_user
from app.dashboard_login import COOKIE_NAME


async def dashboard_guard(request, call_next):
    path = request.url.path

    if path in ("/login", "/api/health"):
        return await call_next(request)

    username = session_user(request.cookies.get(COOKIE_NAME))

    if username is None:
        if path.startswith("/api/") or path.startswith("/videos/"):
            return JSONResponse(
                {"detail": "Authentication required"},
                status_code=401,
            )
        return RedirectResponse("/login", status_code=303)

    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin", "")
        host = request.headers.get("host", "")
        parsed = urlsplit(origin)

        if (
            parsed.scheme != "https"
            or parsed.netloc.lower() != host.lower()
        ):
            return JSONResponse(
                {"detail": "Invalid request origin"},
                status_code=403,
            )

    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
