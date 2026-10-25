import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Stock(Base):
    __tablename__ = "stock"

    id_stock: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    stock: Mapped[int] = mapped_column(Integer)
    caducidad: Mapped[datetime] = mapped_column(DateTime)


class ProductoStock(Base):
    __tablename__ = "productos_stock"

    id_producto_stock: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    id_producto: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("productos.id_producto")
    )
    fecha_registro: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    stock_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stock.id_stock"))
