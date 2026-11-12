import uuid

from sqlalchemy import Float, ForeignKey, ForeignKeyConstraint, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


# Por ahora solo DetallePedido (lo usamos para saber si un producto ya se pidió).
# Aquí irán Pedido y Pago cuando hagamos ese módulo.
class DetallePedido(Base):
    __tablename__ = "detalle_pedidos"

    pedido_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
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
