import uuid

from pydantic import BaseModel, ConfigDict


class DistribuidorOut(BaseModel):
    """Lo único que se expone de un distribuidor a otros usuarios."""

    model_config = ConfigDict(from_attributes=True)
    id_distribuidor: uuid.UUID
    nombre_marca: str
    nombre_encargado: str
    porcentaje_anticipo: float  # para mostrar el anticipo en el carrito antes de confirmar


class DistribuidoresPage(BaseModel):
    distribuidores: list[DistribuidorOut]
    page: int
    page_size: int
    total: int
    total_pages: int
