from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import Conflicto, NoAutenticado
from app.core.security import DUMMY_HASH, hash_password, verify_password
from app.models import Cliente, Distribuidor
from app.schemas.auth import RegistroCliente, RegistroDistribuidor

MSG_CORREO = "Ese correo ya está registrado"


def _correo_existe(db: Session, model, correo: str) -> bool:
    return db.scalar(select(model.correo).where(model.correo == correo)) is not None


def registrar_distribuidor(db: Session, data: RegistroDistribuidor) -> Distribuidor:
    correo = data.correo.lower()
    if _correo_existe(db, Distribuidor, correo):
        raise Conflicto(MSG_CORREO)

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
        raise Conflicto(MSG_CORREO)
    return dist


def registrar_cliente(db: Session, data: RegistroCliente) -> Cliente:
    correo = data.correo.lower()
    if _correo_existe(db, Cliente, correo):
        raise Conflicto(MSG_CORREO)

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
        raise Conflicto(MSG_CORREO)
    return cliente


def autenticar(
    db: Session, correo: str, contrasena: str, rol: str | None = None
) -> tuple[str, str]:
    """Valida credenciales y devuelve (id del usuario como texto, rol).

    Sin `rol` se prueba distribuidor y luego cliente. Siempre se verifica contra ambos
    hashes (o el falso) para que el tiempo no revele si el correo existe ni en qué tabla.
    """
    correo = correo.lower()
    encontrado: tuple[str, str] | None = None
    for r in ([rol] if rol else ["distribuidor", "cliente"]):
        model = Distribuidor if r == "distribuidor" else Cliente
        user = db.scalar(select(model).where(model.correo == correo))
        ok = verify_password(contrasena, user.contrasena if user else DUMMY_HASH)
        if user and ok and encontrado is None:
            uid = user.id_distribuidor if r == "distribuidor" else user.id_cliente
            encontrado = (str(uid), r)

    if encontrado is None:
        raise NoAutenticado("Correo o contraseña incorrectos")
    return encontrado
