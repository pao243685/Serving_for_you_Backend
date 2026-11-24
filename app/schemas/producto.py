import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from app.models.producto import CategoriaPostre
from app.schemas.distribuidor import DistribuidorOut

# ---------------------------------------------------------------- Respuestas


class ProductoPublico(BaseModel):
    """Vista para clientes (cafeterías): solo lo necesario para comprar."""

    model_config = ConfigDict(from_attributes=True)
    id_producto: uuid.UUID
    nombre: str
    tamano: str | None
    descripcion_producto: str | None
    unidad_medida: str
    precio_unitario: float
    imagen_url: str


class ProductoDueno(ProductoPublico):
    """Vista para el distribuidor dueño: todo lo anterior más datos de gestión."""

    categoria: CategoriaPostre
    codigo_generado: str
    activo: bool


class ProductoPublicoStock(ProductoPublico):
    """Producto del catálogo con sus unidades disponibles."""

    stock_disponible: int  # unidades en lotes sin vencer


class ProductoDuenoStock(ProductoDueno):
    stock_disponible: int  # unidades en lotes sin vencer


class ConteosCatalogo(BaseModel):
    """Números de las pestañas del catálogo. Respetan la búsqueda `q` (y `activo` en el
    listado del dueño), pero no los filtros `unidad_medida` ni `categoria`, para que cada
    pestaña muestre su propio total."""

    todos: int
    por_unidad: dict[str, int]  # PZ, KG y L (siempre las tres)
    por_categoria: dict[str, int]  # todas las categorías (siempre todas)


class ProductosPublicosPage(BaseModel):
    distribuidor: DistribuidorOut
    productos: list[ProductoPublicoStock]
    conteos: ConteosCatalogo
    page: int
    page_size: int
    total: int
    total_pages: int


class MisProductosPage(BaseModel):
    productos: list[ProductoDuenoStock]
    conteos: ConteosCatalogo
    page: int
    page_size: int
    total: int
    total_pages: int


# ---------------------------------------------------------------- Entradas


class ProductoCreate(BaseModel):
    nombre: str = Field(min_length=1, max_length=255)
    unidad_medida: Literal["KG", "L", "PZ"]
    tamano: Literal["PEQUEÑO", "MEDIANO", "GRANDE"] | None = None
    precio_unitario: float = Field(gt=0, le=1_000_000)
    categoria: CategoriaPostre
    descripcion_producto: str | None = Field(default=None, max_length=1000)
    imagen_url: HttpUrl

    @field_validator("nombre")
    @classmethod
    def nombre_no_vacio(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("No puede estar vacío")
        return v

    @field_validator("descripcion_producto")
    @classmethod
    def descripcion_limpia(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None


# Campos NOT NULL en la BD: se pueden omitir, pero no mandar null
_NO_NULOS = ("nombre", "unidad_medida", "precio_unitario", "categoria", "imagen_url", "activo")


class ProductoUpdate(BaseModel):
    """PATCH: solo se actualiza lo que venga en el body."""

    model_config = ConfigDict(extra="forbid")

    nombre: str | None = Field(default=None, min_length=1, max_length=255)
    unidad_medida: Literal["KG", "L", "PZ"] | None = None
    tamano: Literal["PEQUEÑO", "MEDIANO", "GRANDE"] | None = None  # null = sin tamaño
    precio_unitario: float | None = Field(default=None, gt=0, le=1_000_000)
    categoria: CategoriaPostre | None = None
    descripcion_producto: str | None = Field(default=None, max_length=1000)  # null = borrar
    imagen_url: HttpUrl | None = None
    activo: bool | None = None

    @field_validator("nombre")
    @classmethod
    def nombre_no_vacio(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("No puede estar vacío")
        return v

    @field_validator("descripcion_producto")
    @classmethod
    def descripcion_limpia(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None

    @model_validator(mode="after")
    def validar_campos(self):
        if not self.model_fields_set:
            raise ValueError("Envía al menos un campo para actualizar")
        for campo in _NO_NULOS:
            if campo in self.model_fields_set and getattr(self, campo) is None:
                raise ValueError(f"{campo} no puede ser null")
        return self
