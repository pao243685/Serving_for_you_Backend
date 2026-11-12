import uuid

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import require_distribuidor
from app.core.database import get_db
from app.core.limiter import limiter
from app.schemas.common import total_paginas
from app.schemas.lote import EstadoLote, LoteCreate, LoteOut, LotesPage, LoteUpdate
from app.services import lotes as lotes_service
from app.services import productos as productos_service

router = APIRouter(tags=["lotes"])


@router.post("/lotes", response_model=LoteOut, status_code=201)
@limiter.limit("30/minute")
def registrar_lote(
    request: Request,
    data: LoteCreate,
    db: Session = Depends(get_db),
    id_distribuidor: uuid.UUID = Depends(require_distribuidor),
):
    """Registra un lote de producción: cantidad producida y fecha de caducidad."""
    return lotes_service.crear(db, id_distribuidor, data)


@router.get("/lotes", response_model=LotesPage)
@limiter.limit("60/minute")
def listar_lotes(
    request: Request,
    estado: EstadoLote = Query(
        default="todos", description="todos | critica (caduca pronto) | por_agotarse"
    ),
    q: str | None = Query(default=None, max_length=100, description="Producto, SKU o código de lote"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    id_distribuidor: uuid.UUID = Depends(require_distribuidor),
):
    items, conteos, total = lotes_service.listar(
        db, id_distribuidor, estado, q, None, page, page_size
    )
    return LotesPage(
        lotes=items,
        conteos=conteos,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_paginas(total, page_size),
    )


@router.get("/productos/{id_producto}/lotes", response_model=LotesPage)
@limiter.limit("60/minute")
def lotes_del_producto(
    request: Request,
    id_producto: uuid.UUID,
    estado: EstadoLote = Query(default="todos"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    id_distribuidor: uuid.UUID = Depends(require_distribuidor),
):
    """Botón "Ver Lotes" de la ficha de producto."""
    productos_service.obtener_propio(db, id_distribuidor, id_producto)  # 404 si no es suyo
    items, conteos, total = lotes_service.listar(
        db, id_distribuidor, estado, None, id_producto, page, page_size
    )
    return LotesPage(
        lotes=items,
        conteos=conteos,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_paginas(total, page_size),
    )


@router.get("/lotes/{id_stock}", response_model=LoteOut)
@limiter.limit("60/minute")
def detalle_lote(
    request: Request,
    id_stock: uuid.UUID,
    db: Session = Depends(get_db),
    id_distribuidor: uuid.UUID = Depends(require_distribuidor),
):
    return lotes_service.obtener(db, id_distribuidor, id_stock)


@router.patch("/lotes/{id_stock}", response_model=LoteOut)
@limiter.limit("30/minute")
def editar_lote(
    request: Request,
    id_stock: uuid.UUID,
    data: LoteUpdate,
    db: Session = Depends(get_db),
    id_distribuidor: uuid.UUID = Depends(require_distribuidor),
):
    """Ajusta existencias o caducidad. Para dar un lote por agotado: {"stock": 0}."""
    return lotes_service.editar(db, id_distribuidor, id_stock, data)


@router.delete("/lotes/{id_stock}", status_code=204)
@limiter.limit("30/minute")
def borrar_lote(
    request: Request,
    id_stock: uuid.UUID,
    db: Session = Depends(get_db),
    id_distribuidor: uuid.UUID = Depends(require_distribuidor),
):
    lotes_service.borrar(db, id_distribuidor, id_stock)
    return Response(status_code=204)
