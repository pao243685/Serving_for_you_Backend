import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.producto import Producto


class Distribuidor(Base):
    __tablename__ = "distribuidores"

    id_distribuidor: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    nombre_marca: Mapped[str] = mapped_column(String(100))
    nombre_encargado: Mapped[str] = mapped_column(String(200))
    correo: Mapped[str] = mapped_column(Text, unique=True)
    contrasena: Mapped[str] = mapped_column(Text)
    telefono: Mapped[str] = mapped_column(String(10))
    direccion_local: Mapped[str] = mapped_column(Text)
    terminos_condiciones: Mapped[bool] = mapped_column(Boolean, default=False)
    banco: Mapped[str | None] = mapped_column(String(100))
    titular: Mapped[str | None] = mapped_column(String(200))
    clabe: Mapped[str | None] = mapped_column(String(18))
    porcentaje_anticipo: Mapped[float] = mapped_column(Numeric(5, 2), default=50)

    productos: Mapped[list["Producto"]] = relationship(back_populates="distribuidor")
