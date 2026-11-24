import uuid

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import decode_token

bearer = HTTPBearer(
    auto_error=False,
    bearerFormat="JWT",
    description=(
        "Pega el access_token que devuelve POST /auth/login "
        "(solo el token, sin la palabra Bearer)."
    ),
)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> dict:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Falta el token de acceso")
    try:
        return decode_token(creds.credentials)
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido o expirado") from None


def require_distribuidor(user: dict = Depends(get_current_user)) -> uuid.UUID:
    """Exige rol distribuidor y devuelve su id (sacado del token)."""
    if user.get("rol") != "distribuidor":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Solo los distribuidores pueden hacer esto"
        )
    try:
        return uuid.UUID(user["sub"])
    except (KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido") from None


def require_cliente(user: dict = Depends(get_current_user)) -> uuid.UUID:
    """Exige rol cliente y devuelve su id (sacado del token)."""
    if user.get("rol") != "cliente":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo los clientes pueden hacer esto")
    try:
        return uuid.UUID(user["sub"])
    except (KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido") from None
