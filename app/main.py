from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.routers import auth, distribuidores, productos
from app.core.config import settings
from app.core.exceptions import AppError
from app.core.limiter import limiter
from app.core.middleware import origin_firewall

app = FastAPI(title="Serving for you API", version="1.1.0")

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


# Errores de negocio (los lanzan los services) -> respuesta HTTP
@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


# Firewall de origen (se activa cuando llenes ALLOWED_ORIGINS)
app.middleware("http")(origin_firewall)

# CORS va al final para que sea la capa más externa
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(auth.router)
app.include_router(distribuidores.router)
app.include_router(productos.router)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}
