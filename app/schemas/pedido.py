import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

TabPedidos = Literal["activos", "entregados", "cancelados"]


# ---------------------------------------------------------------- Entradas


class PedidoItemIn(BaseModel):
    id_producto: uuid.UUID
    cantidad: int = Field(gt=0, le=10_000)


class PedidoCreate(BaseModel):
    id_distribuidor: uuid.UUID
    direccion_entrega: str = Field(min_length=1, max_length=500)
    items: list[PedidoItemIn] = Field(min_length=1, max_length=50)

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


class CancelarIn(BaseModel):
    motivo: str | None = Field(default=None, max_length=500)

    @field_validator("motivo")
    @classmethod
    def motivo_limpio(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None


# ---------------------------------------------------------------- Respuestas


class ClienteDePedido(BaseModel):
    id_cliente: uuid.UUID
    nombre: str
    telefono: str


class DistribuidorDePedido(BaseModel):
    """Incluye los datos bancarios: el cliente los necesita para pagar el anticipo."""

    id_distribuidor: uuid.UUID
    nombre_marca: str
    telefono: str
    banco: str | None
    titular: str | None
    clabe: str | None


class LineaPedido(BaseModel):
    id_producto: uuid.UUID
    nombre: str
    tamano: str | None
    unidad_medida: str
    imagen_url: str
    cantidad: int
    precio_unitario: float
    subtotal: float


class PagoOut(BaseModel):
    id_pago: uuid.UUID
    tipo: Literal["ANTICIPO", "FINAL"]
    monto: float
    estado: str
    metodo: str
    referencia: str
    comprobante_url: str | None
    motivo_rechazo: str | None
    fecha_creacion: datetime
    fecha_comprobante: datetime | None
    fecha_validacion: datetime | None
    fecha_reembolso: datetime | None


class PedidoOut(BaseModel):
    id_pedido: uuid.UUID
    folio: str  # corto y derivado del id (la BD no guarda uno): PED-1A2B3C4D
    estatus: str
    # Paso del stepper del front: 1 Confirmado y anticipo, 2 En preparación,
    # 3 En ruta, 4 Recepción y liquidación. None si está cancelado.
    paso: int | None
    cliente: ClienteDePedido
    distribuidor: DistribuidorDePedido
    direccion_entrega: str
    fecha_realizacion: datetime
    fecha_entrega_estimada: datetime | None
    fecha_entrega_real: datetime | None
    fecha_cancelacion: datetime | None
    cancelado_por: str | None
    motivo_cancelacion: str | None
    lineas: list[LineaPedido]
    total_unidades: int
    total_productos: float
    pagos: list[PagoOut]
    anticipo_pagado: bool  # el proveedor ya confirmó el anticipo
    saldo_restante: float  # lo que falta por liquidar contra entrega
    cancelable_por_cliente: bool
    reembolso_pendiente: bool  # cancelado con anticipo ya confirmado, falta devolverlo


class ConteosPedidos(BaseModel):
    """Números de las pestañas Activos / Entregados / Cancelados."""

    activos: int
    entregados: int
    cancelados: int


class ResumenMisPedidos(BaseModel):
    en_ruta: int  # pedidos EN_ENVIO
    en_armado: int  # pedidos EN_PROCESO
    saldo_por_liquidar: float  # pago final pendiente de los pedidos EN_ENVIO


class MisPedidosPage(BaseModel):
    pedidos: list[PedidoOut]
    conteos: ConteosPedidos
    resumen: ResumenMisPedidos
    page: int
    page_size: int
    total: int
    total_pages: int
