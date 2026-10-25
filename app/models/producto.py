import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.distribuidor import Distribuidor


class CategoriaPostre(str, enum.Enum):
    PASTELES = "Pasteles"
    GELATINAS_FLANES = "Gelatinas y Flanes"
    HELADOS = "Helados"
    GALLETAS = "Galletas"
    MOUSSE_CREMAS = "Mousse y Cremas"
    PANADERIA_DULCE = "Panadería Dulce"


class Producto(Base):
    __tablename__ = "productos"

    id_producto: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    imagen_url: Mapped[str] = mapped_column(Text)
    nombre: Mapped[str] = mapped_column(String(255))
    unidad_medida: Mapped[str] = mapped_column(String(20))
    tamano: Mapped[str | None] = mapped_column(String(20))
    id_distribuidor: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("distribuidores.id_distribuidor")
    )
    precio_unitario: Mapped[float] = mapped_column(Float)
    codigo_generado: Mapped[str] = mapped_column(String(12))
    categoria: Mapped[CategoriaPostre] = mapped_column(
        Enum(
            CategoriaPostre,
            name="categoria_postre",
            create_type=False,  # el tipo ya existe en la BD
            values_callable=lambda e: [m.value for m in e],
        )
    )
    descripcion_producto: Mapped[str | None] = mapped_column(Text)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    # gramaje: Mapped[float | None] = mapped_column(Numeric(10, 2))  # si agregas la columna

    distribuidor: Mapped["Distribuidor"] = relationship(back_populates="productos")
