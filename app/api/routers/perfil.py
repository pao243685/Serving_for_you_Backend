from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.limiter import limiter
from app.schemas.perfil import PerfilOut
from app.services import perfil as perfil_service

router = APIRouter(tags=["auth"])


@router.get("/me", response_model=PerfilOut)
@limiter.limit("60/minute")
def mi_perfil(
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Quién tiene la sesión abierta. Alimenta la cabecera de todas las pantallas
    (nombre y negocio) y, para el distribuidor, trae también sus datos bancarios y
    su porcentaje de anticipo."""
    return perfil_service.obtener(db, user)
