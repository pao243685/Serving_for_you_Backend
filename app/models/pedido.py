import uuid

from sqlalchemy import Float, ForeignKey, Integer
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
