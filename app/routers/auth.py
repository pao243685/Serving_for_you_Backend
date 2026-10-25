from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.limiter import limiter
from app.models import Cliente, Distribuidor
from app.schemas import LoginIn, RegistroCliente, RegistroDistribuidor, TokenOut, UsuarioOut
from app.security import DUMMY_HASH, create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


def _correo_existe(db: Session, model, correo: str) -> bool:
    return db.scalar(select(model.correo).where(model.correo == correo)) is not None


@router.post("/registro/distribuidor", response_model=UsuarioOut, status_code=201)
@limiter.limit(settings.rate_limit_auth)
def registro_distribuidor(
    request: Request, data: RegistroDistribuidor, db: Session = Depends(get_db)
):
    correo = data.correo.lower()
    if _correo_existe(db, Distribuidor, correo):
        raise HTTPException(status.HTTP_409_CONFLICT, "Ese correo ya está registrado")

    dist = Distribuidor(
        **data.model_dump(exclude={"correo", "contrasena"}),
        correo=correo,
        contrasena=hash_password(data.contrasena),
    )
    db.add(dist)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Ese correo ya está registrado")
    return UsuarioOut(id=dist.id_distribuidor, correo=dist.correo, rol="distribuidor")


@router.post("/registro/cliente", response_model=UsuarioOut, status_code=201)
@limiter.limit(settings.rate_limit_auth)
def registro_cliente(request: Request, data: RegistroCliente, db: Session = Depends(get_db)):
    correo = data.correo.lower()
    if _correo_existe(db, Cliente, correo):
        raise HTTPException(status.HTTP_409_CONFLICT, "Ese correo ya está registrado")

    cliente = Cliente(
        nombre=data.nombre,
        correo=correo,
        contrasena=hash_password(data.contrasena),
        telefono=data.telefono,
    )
    db.add(cliente)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Ese correo ya está registrado")
    return UsuarioOut(id=cliente.id_cliente, correo=cliente.correo, rol="cliente")


@router.post("/login", response_model=TokenOut)
@limiter.limit(settings.rate_limit_auth)
def login(request: Request, data: LoginIn, db: Session = Depends(get_db)):
    model = Distribuidor if data.rol == "distribuidor" else Cliente
    user = db.scalar(select(model).where(model.correo == data.correo.lower()))

    # Verificamos siempre para que el tiempo de respuesta no revele si el correo existe
    ok = verify_password(data.contrasena, user.contrasena if user else DUMMY_HASH)
    if not user or not ok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Correo o contraseña incorrectos")

    user_id = user.id_distribuidor if data.rol == "distribuidor" else user.id_cliente
    return TokenOut(access_token=create_access_token(str(user_id), data.rol), rol=data.rol)
