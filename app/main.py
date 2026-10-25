from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import settings
from app.limiter import limiter
from app.middleware import origin_firewall
from app.routers import auth, productos

app = FastAPI(title="Serving for you API", version="1.0.0")

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

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
app.include_router(productos.router)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}
