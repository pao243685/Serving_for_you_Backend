from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.schemas.pago import _validar_comprobante
from app.schemas.pedido import PedidoItemIn, PedidoOut

TabPedidosDistribuidor = Literal["todos", "pendiente", "en_envio", "entregado", "cancelado"]


# ---------------------------------------------------------------- Entradas


class CancelarProveedorIn(BaseModel):
    motivo: str = Field(min_length=1, max_length=500)

    @field_validator("motivo")
    @classmethod
    def motivo_limpio(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Indica el motivo de la cancelación")
        return v


class PedidoManualIn(BaseModel):
    """'Generar orden manual': el distribuidor captura un pedido a nombre de un cliente
    que ya está registrado (por ejemplo, un pedido por teléfono)."""

    correo_cliente: EmailStr
    direccion_entrega: str = Field(min_length=1, max_length=500)
    items: list[PedidoItemIn] = Field(min_length=1, max_length=50)

    @field_validator("correo_cliente")
    @classmethod
    def correo_minusculas(cls, v: str) -> str:
        return v.lower()

    @field_validator("direccion_entrega")
    @classmethod
    def direccion_limpia(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("No puede estar vacío")
        return v

    @model_validator(mode="after")
    def sin_repetidos(self):
        ids = [i.id_producto for i in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Cada producto debe aparecer una sola vez; suma las cantidades")
        return self


class PedidoManualCobroUnicoIn(PedidoManualIn):
    """'Pedido manual cobro único': venta directa que captura el distribuidor. Puede ir a nombre de
    un cliente registrado (correo_cliente) o, sin correo, de un comprador sin cuenta. No hay
    anticipo ni saldo: se cobra todo de una vez y el pedido nace ENTREGADO."""

    # Sin correo, la venta se registra a nombre del cliente genérico «Venta de mostrador»
    correo_cliente: EmailStr | None = None
    direccion_entrega: str = Field(default="Venta en mostrador", min_length=1, max_length=500)
    metodo: Literal["EFECTIVO", "TRANSFERENCIA"]
    comprobante_url: str | None = None

    @field_validator("correo_cliente")
    @classmethod
    def correo_minusculas(cls, v: str | None) -> str | None:
        return v.lower() if v is not None else None

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


class ConteosPedidosDistribuidor(BaseModel):
    todos: int
    pendiente: int  # PENDIENTE, POR_VALIDAR y EN_PROCESO: todavía no sale a ruta
    en_envio: int
    entregado: int
    cancelado: int


class PedidosDistribuidorPage(BaseModel):
    pedidos: list[PedidoOut]
    conteos: ConteosPedidosDistribuidor  # para las pestañas: respetan la búsqueda `q`
    resumen: ConteosPedidosDistribuidor  # para las tarjetas de arriba: siempre globales
    page: int
    page_size: int
    total: int
    total_pages: int
