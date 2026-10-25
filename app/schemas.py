import math
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, field_validator, model_validator

from app.models import CategoriaPostre

Telefono = Field(pattern=r"^[0-9]{10}$")


class RegistroCliente(BaseModel):
    nombre: str = Field(min_length=1, max_length=200)
    correo: EmailStr
    contrasena: str = Field(min_length=8, max_length=128)
    telefono: str = Telefono

    @field_validator("nombre")
    @classmethod
    def nombre_no_vacio(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("No puede estar vacío")
        return v


class RegistroDistribuidor(BaseModel):
    nombre_marca: str = Field(min_length=1, max_length=100)
    nombre_encargado: str = Field(min_length=1, max_length=200)
    correo: EmailStr
    contrasena: str = Field(min_length=8, max_length=128)
    telefono: str = Telefono
    direccion_local: str = Field(min_length=1)
    terminos_condiciones: bool
    banco: str | None = Field(default=None, max_length=100)
    titular: str | None = Field(default=None, max_length=200)
    clabe: str | None = Field(default=None, pattern=r"^[0-9]{18}$")
    porcentaje_anticipo: float = Field(default=50, gt=0, le=100)

    @field_validator("nombre_marca", "nombre_encargado", "direccion_local")
    @classmethod
    def no_vacio(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("No puede estar vacío")
        return v

    @field_validator("terminos_condiciones")
    @classmethod
    def acepta_terminos(cls, v: bool) -> bool:
        if not v:
            raise ValueError("Debes aceptar los términos y condiciones")
        return v

    @model_validator(mode="after")
    def datos_bancarios_completos(self):
        campos = [self.banco, self.titular, self.clabe]
        if any(campos) and not all(campos):
            raise ValueError("banco, titular y clabe deben enviarse juntos o ninguno")
        return self


class LoginIn(BaseModel):
    correo: EmailStr
    contrasena: str
    rol: Literal["distribuidor", "cliente"]


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    rol: str


class UsuarioOut(BaseModel):
    id: uuid.UUID
    correo: str
    rol: str


class DistribuidorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id_distribuidor: uuid.UUID
    nombre_marca: str
    nombre_encargado: str


class ProductoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id_producto: uuid.UUID
    nombre: str
    precio_unitario: float
    unidad_medida: str
    tamano: str | None
    categoria: CategoriaPostre
    descripcion_producto: str | None
    imagen_url: str
    # gramaje: float | None = None  # si agregas la columna


class ProductosPage(BaseModel):
    distribuidor: DistribuidorOut
    productos: list[ProductoOut]
    page: int
    page_size: int
    total: int
    total_pages: int

    @staticmethod
    def pages(total: int, page_size: int) -> int:
        return math.ceil(total / page_size) if total else 0

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


class ProductoCreado(ProductoOut):
    codigo_generado: str
    activo: bool