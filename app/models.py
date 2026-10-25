import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class CategoriaPostre(str, enum.Enum):
    PASTELES = "Pasteles"
    GELATINAS_FLANES = "Gelatinas y Flanes"
    HELADOS = "Helados"
    GALLETAS = "Galletas"
    MOUSSE_CREMAS = "Mousse y Cremas"
    PANADERIA_DULCE = "Panadería Dulce"


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


class Cliente(Base):
    __tablename__ = "clientes"

    id_cliente: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    nombre: Mapped[str] = mapped_column(String(200))
    correo: Mapped[str] = mapped_column(Text, unique=True)
    contrasena: Mapped[str] = mapped_column(Text)
    telefono: Mapped[str] = mapped_column(String(10))


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

    distribuidor: Mapped[Distribuidor] = relationship(back_populates="productos")


# --- Tablas de apoyo (por ahora solo se usan para borrar productos sin dejar basura) ---


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


class DetallePedido(Base):
    __tablename__ = "detalle_pedidos"

    pedido_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    producto_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("productos.id_producto"), primary_key=True
    )
    cantidad: Mapped[int] = mapped_column(Integer)
    precio_unitario: Mapped[float] = mapped_column(Float)