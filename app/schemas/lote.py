import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Vigencia(str, Enum):
    """Etiqueta de caducidad para pintar el badge del front."""

    VENCIDO = "VENCIDO"
    ULTIMAS_HORAS = "ULTIMAS_HORAS"  # <= 12 h        (rojo)
    CONSUMO_RAPIDO = "CONSUMO_RAPIDO"  # <= 48 h      (naranja)
    FRESCURA_OPTIMA = "FRESCURA_OPTIMA"  # <= 7 días  (verde)
    LARGA_VIDA = "LARGA_VIDA"  # > 7 días             (azul)


def a_utc_naive(dt: datetime) -> datetime:
    """La columna `caducidad` es TIMESTAMP sin zona: guardamos siempre UTC.
    Si el front manda fecha sin zona horaria, se toma como UTC."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


# ---------------------------------------------------------------- Respuestas


class ProductoDeLote(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id_producto: uuid.UUID
    nombre: str
    tamano: str | None
    unidad_medida: str
    codigo_generado: str


class LoteOut(BaseModel):
    id_stock: uuid.UUID
    codigo_lote: str  # corto y derivado del id (la BD no guarda un código propio)
    producto: ProductoDeLote
    stock: int
    caducidad: datetime
    fecha_registro: datetime
    vigencia: Vigencia
    por_agotarse: bool


class ConteosLotes(BaseModel):
    """Números de las pestañas (respetan la búsqueda y el filtro de producto)."""

    todos: int
    critica: int
    por_agotarse: int


class LotesPage(BaseModel):
    lotes: list[LoteOut]
    conteos: ConteosLotes
    page: int
    page_size: int
    total: int
    total_pages: int


# ---------------------------------------------------------------- Entradas


class LoteCreate(BaseModel):
    id_producto: uuid.UUID
    stock: int = Field(gt=0, le=1_000_000, description="Cantidad producida")
    caducidad: datetime

    @field_validator("caducidad")
    @classmethod
    def caducidad_futura(cls, v: datetime) -> datetime:
        v = a_utc_naive(v)
        if v <= datetime.now(timezone.utc).replace(tzinfo=None):
            raise ValueError("La caducidad debe ser una fecha futura")
        return v


class LoteUpdate(BaseModel):
    """PATCH: ajusta existencias o caducidad de un lote."""

    model_config = ConfigDict(extra="forbid")

    stock: int | None = Field(default=None, ge=0, le=1_000_000)
    caducidad: datetime | None = None

    @field_validator("caducidad")
    @classmethod
    def caducidad_utc(cls, v: datetime | None) -> datetime | None:
        return a_utc_naive(v) if v is not None else v

    @model_validator(mode="after")
    def validar(self):
        if not self.model_fields_set:
            raise ValueError("Envía al menos un campo para actualizar")
        for campo in ("stock", "caducidad"):
            if campo in self.model_fields_set and getattr(self, campo) is None:
                raise ValueError(f"{campo} no puede ser null")
        return self


EstadoLote = Literal["todos", "critica", "por_agotarse"]
