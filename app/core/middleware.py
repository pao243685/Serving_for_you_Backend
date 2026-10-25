from urllib.parse import urlparse

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.config import settings

# Rutas que no exigen origen (el healthcheck del servidor, por ejemplo)
EXEMPT_PATHS = {"/health"}


async def origin_firewall(request: Request, call_next):
    allowed = settings.origins_list
    if not allowed or request.url.path in EXEMPT_PATHS:
        return await call_next(request)

    origin = request.headers.get("origin")
    if not origin:
        referer = request.headers.get("referer")
        if referer:
            p = urlparse(referer)
            origin = f"{p.scheme}://{p.netloc}"

    if origin is None or origin.rstrip("/") not in allowed:
        return JSONResponse({"detail": "Acceso no permitido"}, status_code=403)

    return await call_next(request)
