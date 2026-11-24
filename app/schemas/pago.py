import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, TypeAdapter, field_validator, model_validator

from app.schemas.pedido import PedidoOut

_URL = TypeAdapter(HttpUrl)
# Misma regla que el CHECK de la tabla pagos
_EXTENSION = re.compile(r"\.(jpe?g|png|pdf)(\?.*)?$", re.IGNORECASE)


def _validar_comprobante(v: str) -> str:
    v = v.strip()
    if len(v) > 2048:
        raise ValueError("El enlace es demasiado largo")
    if not v.lower().startswith("https://"):
        raise ValueError("El enlace debe empezar con https://")
    url = str(_URL.validate_python(v))
    if not _EXTENSION.search(url):
        raise ValueError("El comprobante debe ser una imagen (.jpg, .jpeg, .png) o un .pdf")
    return url


TabCobranza = Literal[
    "todos", "anticipos_por_confirmar", "pendiente_liquidar", "pagados", "reembolsos"
]


# ---------------------------------------------------------------- Entradas


class ComprobanteIn(BaseModel):
    comprobante_url: str

    @field_validator("comprobante_url")
    @classmethod
    def url_valida(cls, v: str) -> str:
        return _validar_comprobante(v)


class ValidarAnticipoIn(BaseModel):
    """Al validar el anticipo el proveedor fija cuándo entregará."""

    fecha_entrega_estimada: datetime

    @field_validator("fecha_entrega_estimada")
    @classmethod
    def futura(cls, v: datetime) -> datetime:
        if v.tzinfo is None:  # sin zona horaria se toma como UTC
            v = v.replace(tzinfo=UTC)
        v = v.astimezone(UTC)
        if v <= datetime.now(UTC):
            raise ValueError("La fecha de entrega debe ser futura")
        return v


class RechazarIn(BaseModel):
    motivo: str = Field(min_length=1, max_length=500)

    @field_validator("motivo")
    @classmethod
    def motivo_limpio(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Indica el motivo del rechazo")
        return v


class LiquidacionIn(BaseModel):
    """Cobro del saldo contra entrega. La transferencia exige comprobante."""

    metodo: Literal["EFECTIVO", "TRANSFERENCIA"]
    comprobante_url: str | None = None

    @field_validator("comprobante_url")
    @classmethod
    def url_valida(cls, v: str | None) -> str | None:
        return _validar_comprobante(v) if v is not None else None

    @model_validator(mode="after")
    def transferencia_con_comprobante(self):
        if self.metodo == "TRANSFERENCIA" and not self.comprobante_url:
            raise ValueError("Una transferencia necesita el comprobante")
        return self


# ---------------------------------------------------------------- Respuestas


class ConteosCobranza(BaseModel):
    """Números de las pestañas (respetan la búsqueda)."""

    todos: int
    anticipos_por_confirmar: int
    pendiente_liquidar: int
    pagados: int
    reembolsos: int


class ResumenCobranza(BaseModel):
    total_vendido_semana: float  # pedidos no cancelados de los últimos 7 días
    anticipos_cobrados: float  # anticipos confirmados de esos mismos pedidos
    saldos_pendientes: float  # saldo por liquidar de todos los pedidos con anticipo confirmado
    liquidaciones_hoy: float  # saldos cobrados hoy


class CobranzaPage(BaseModel):
    pedidos: list[PedidoOut]
    conteos: ConteosCobranza
    resumen: ResumenCobranza
    page: int
    page_size: int
    total: int
    total_pages: int
