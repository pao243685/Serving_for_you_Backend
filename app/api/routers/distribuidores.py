import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.limiter import limiter
from app.models import CategoriaPostre
from app.schemas.common import total_paginas
from app.schemas.distribuidor import DistribuidoresPage
from app.schemas.producto import ProductosPublicosPage
from app.services import distribuidores as distribuidores_service
from app.services import productos as productos_service

router = APIRouter(tags=["distribuidores"])


@router.get("/distribuidores", response_model=DistribuidoresPage)
@limiter.limit("60/minute")
def listar_distribuidores(
    request: Request,
    q: str | None = Query(default=None, max_length=100, description="Busca por nombre de marca"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    items, total = distribuidores_service.listar(db, q, page, page_size)
    return DistribuidoresPage(
        distribuidores=items,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_paginas(total, page_size),
    )


@router.get("/distribuidores/{id_distribuidor}/productos", response_model=ProductosPublicosPage)
@limiter.limit("60/minute")
def catalogo_del_distribuidor(
    request: Request,
    id_distribuidor: uuid.UUID,
    categoria: CategoriaPostre | None = Query(default=None, description="Filtra por categoría"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """Catálogo público: solo productos activos y solo los campos que ve un cliente."""
    dist = distribuidores_service.obtener(db, id_distribuidor)
    items, total = productos_service.listar(
        db, id_distribuidor, categoria, activo=True, page=page, page_size=page_size
    )
    return ProductosPublicosPage(
        distribuidor=dist,
        productos=items,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_paginas(total, page_size),
    )
