import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, ForeignKeyConstraint, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DetallePedido(Base):
    __tablename__ = "detalle_pedidos"

    pedido_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pedidos.id_pedido"), primary_key=True
    )
    producto_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("productos.id_producto"), primary_key=True
    )
    cantidad: Mapped[int] = mapped_column(Integer)
    precio_unitario: Mapped[float] = mapped_column(Float)


class DetallePedidoLote(Base):
    """Qué lotes (y cuántas unidades de cada uno) se asignaron a cada línea de pedido."""

    __tablename__ = "detalle_pedido_lotes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["pedido_id", "producto_id"],
            ["detalle_pedidos.pedido_id", "detalle_pedidos.producto_id"],
        ),
    )

    pedido_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    producto_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    stock_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stock.id_stock"), primary_key=True
    )
    cantidad: Mapped[int] = mapped_column(Integer)


class Pedido(Base):
    __tablename__ = "pedidos"

    id_pedido: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    cliente_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clientes.id_cliente")
    )
    distribuidor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("distribuidores.id_distribuidor")
    )
    # PENDIENTE, POR_VALIDAR, EN_PROCESO, EN_ENVIO, ENTREGADO, CANCELADO
    estatus: Mapped[str] = mapped_column(String(20), default="PENDIENTE")
    direccion_entrega: Mapped[str] = mapped_column(Text)
    fecha_realizacion: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    fecha_entrega_estimada: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fecha_entrega_real: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelado_por: Mapped[str | None] = mapped_column(String(10))  # CLIENTE, PROVEEDOR, SISTEMA
    motivo_cancelacion: Mapped[str | None] = mapped_column(Text)
    fecha_cancelacion: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Pago(Base):
    __tablename__ = "pagos"

    id_pago: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    pedido_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pedidos.id_pedido")
    )
    tipo: Mapped[str] = mapped_column(String(10))  # ANTICIPO, FINAL
    monto: Mapped[float] = mapped_column(Float)
    # PENDIENTE, POR_VALIDAR, CONFIRMADO, RECHAZADO, ANULADO
    estado: Mapped[str] = mapped_column(String(20), default="PENDIENTE")
    metodo: Mapped[str] = mapped_column(String(20), default="TRANSFERENCIA")  # o EFECTIVO
    referencia: Mapped[str] = mapped_column(String(20))
    comprobante_url: Mapped[str | None] = mapped_column(Text)
    motivo_rechazo: Mapped[str | None] = mapped_column(Text)
    fecha_creacion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    fecha_comprobante: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fecha_validacion: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    comprobante_reembolso_url: Mapped[str | None] = mapped_column(Text)
    fecha_reembolso: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
