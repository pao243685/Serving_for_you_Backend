import uuid

from sqlalchemy.orm import Session

from app.core.exceptions import NoAutenticado
from app.models import Cliente, Distribuidor
from app.schemas.perfil import DatosDistribuidor, PerfilOut


def obtener(db: Session, user: dict) -> PerfilOut:
    """Datos de quien tiene el token. Si el usuario ya no existe, el token deja de servir."""
    try:
        uid = uuid.UUID(user["sub"])
    except (KeyError, ValueError):
        raise NoAutenticado("Token inválido") from None

    if user.get("rol") == "distribuidor":
        d = db.get(Distribuidor, uid)
        if d is None:
            raise NoAutenticado("Usuario no encontrado")
        return PerfilOut(
            id=d.id_distribuidor,
            rol="distribuidor",
            nombre=d.nombre_encargado,
            negocio=d.nombre_marca,
            correo=d.correo,
            telefono=d.telefono,
            distribuidor=DatosDistribuidor(
                nombre_encargado=d.nombre_encargado,
                direccion_local=d.direccion_local,
                banco=d.banco,
                titular=d.titular,
                clabe=d.clabe,
                porcentaje_anticipo=float(d.porcentaje_anticipo),
            ),
        )

    if user.get("rol") == "cliente":
        c = db.get(Cliente, uid)
        if c is None:
            raise NoAutenticado("Usuario no encontrado")
        return PerfilOut(
            id=c.id_cliente,
            rol="cliente",
            nombre=c.nombre,
            negocio=c.nombre,
            correo=c.correo,
            telefono=c.telefono,
        )

    raise NoAutenticado("Token inválido")
