import uuid

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_distribuidor
from app.core.database import get_db
from app.core.limiter import limiter
from app.models import CategoriaPostre
from app.schemas.common import total_paginas
from app.schemas.producto import (
    MisProductosPage,
    ProductoCreate,
    ProductoDueno,
    ProductoUpdate,
)
from app.services import productos as productos_service

router = APIRouter(tags=["productos"])


@router.post("/productos", response_model=ProductoDueno, status_code=201)
@limiter.limit("30/minute")
def crear_producto(
    request: Request,
    data: ProductoCreate,
    db: Session = Depends(get_db),
    id_distribuidor: uuid.UUID = Depends(require_distribuidor),
):
    return productos_service.crear(db, id_distribuidor, data)


@router.patch("/productos/{id_producto}", response_model=ProductoDueno)
@limiter.limit("30/minute")
def editar_producto(
    request: Request,
    id_producto: uuid.UUID,
    data: ProductoUpdate,
    db: Session = Depends(get_db),
    id_distribuidor: uuid.UUID = Depends(require_distribuidor),
):
    """Edita campos sueltos. Para desactivar: {"activo": false}. Para reactivar: {"activo": true}."""
    return productos_service.editar(db, id_distribuidor, id_producto, data)


@router.delete("/productos/{id_producto}", status_code=204)
@limiter.limit("30/minute")
def borrar_producto(
    request: Request,
    id_producto: uuid.UUID,
    db: Session = Depends(get_db),
    id_distribuidor: uuid.UUID = Depends(require_distribuidor),
):
    """Borrado real, solo si el producto nunca se ha pedido. Si ya tiene pedidos, desactívalo."""
    productos_service.borrar(db, id_distribuidor, id_producto)
    return Response(status_code=204)


@router.get("/mis-productos", response_model=MisProductosPage)
@limiter.limit("60/minute")
def mis_productos(
    request: Request,
    categoria: CategoriaPostre | None = Query(default=None, description="Filtra por categoría"),
    activo: bool | None = Query(
        default=None, description="true = solo activos, false = solo desactivados, vacío = todos"
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    id_distribuidor: uuid.UUID = Depends(require_distribuidor),
):
    items, total = productos_service.listar(
        db, id_distribuidor, categoria, activo=activo, page=page, page_size=page_size
    )
    return MisProductosPage(
        productos=items,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_paginas(total, page_size),
    )


@router.get("/categorias", response_model=list[str])
@limiter.limit("60/minute")
def listar_categorias(request: Request, _user: dict = Depends(get_current_user)):
    return [c.value for c in CategoriaPostre]
