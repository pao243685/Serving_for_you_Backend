import uuid
from typing import Literal

from pydantic import BaseModel


class DatosDistribuidor(BaseModel):
    """Solo para el rol distribuidor."""

    nombre_encargado: str
    direccion_local: str
    banco: str | None
    titular: str | None
    clabe: str | None
    porcentaje_anticipo: float


class PerfilOut(BaseModel):
    id: uuid.UUID
    rol: Literal["cliente", "distribuidor"]
    nombre: str  # lo que muestra la cabecera: el encargado (distribuidor) o el negocio (cliente)
    negocio: str  # nombre de la marca (distribuidor) o de la cafetería (cliente)
    correo: str
    telefono: str
    distribuidor: DatosDistribuidor | None = None
