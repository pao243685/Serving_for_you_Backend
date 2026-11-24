from urllib.parse import urlparse

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.config import settings

# Rutas que no exigen origen: el healthcheck del servidor y la documentación
# (la documentación solo existe si DOCS_ENABLED=true)
EXEMPT_PATHS = {"/health", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}


def _ruta(request: Request) -> str:
    """Ruta sin el prefijo del proxy. En producción Caddy publica la API bajo /api y
    uvicorn corre con root_path=/api: request.url.path llega como /api/health."""
    path = request.url.path
    root = request.scope.get("root_path", "").rstrip("/")
    if root and (path == root or path.startswith(root + "/")):
        path = path[len(root):] or "/"
    return path


async def origin_firewall(request: Request, call_next):
    allowed = settings.origins_list
    if not allowed or _ruta(request) in EXEMPT_PATHS:
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
