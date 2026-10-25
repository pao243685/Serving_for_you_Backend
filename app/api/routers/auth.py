from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.limiter import limiter
from app.core.security import create_access_token
from app.schemas.auth import (
    LoginIn,
    RegistroCliente,
    RegistroDistribuidor,
    TokenOut,
    UsuarioOut,
)
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/registro/distribuidor", response_model=UsuarioOut, status_code=201)
@limiter.limit(settings.rate_limit_auth)
def registro_distribuidor(
    request: Request, data: RegistroDistribuidor, db: Session = Depends(get_db)
):
    dist = auth_service.registrar_distribuidor(db, data)
    return UsuarioOut(id=dist.id_distribuidor, correo=dist.correo, rol="distribuidor")


@router.post("/registro/cliente", response_model=UsuarioOut, status_code=201)
@limiter.limit(settings.rate_limit_auth)
def registro_cliente(request: Request, data: RegistroCliente, db: Session = Depends(get_db)):
    cliente = auth_service.registrar_cliente(db, data)
    return UsuarioOut(id=cliente.id_cliente, correo=cliente.correo, rol="cliente")


@router.post("/login", response_model=TokenOut)
@limiter.limit(settings.rate_limit_auth)
def login(request: Request, data: LoginIn, db: Session = Depends(get_db)):
    user_id = auth_service.autenticar(db, data.correo, data.contrasena, data.rol)
    return TokenOut(access_token=create_access_token(user_id, data.rol), rol=data.rol)
