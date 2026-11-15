import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_cliente
from app.core.database import get_db
from app.core.limiter import limiter
from app.schemas.pedido import (
    CancelarIn,
    MisPedidosPage,
    PedidoCreate,
    PedidoOut,
    TabPedidos,
)
from app.services import pedidos as pedidos_service

router = APIRouter(tags=["pedidos"])


@router.post("/pedidos", response_model=PedidoOut, status_code=201)
@limiter.limit("20/minute")
def crear_pedido(
    request: Request,
    data: PedidoCreate,
    db: Session = Depends(get_db),
    id_cliente: uuid.UUID = Depends(require_cliente),
):
    """Confirma el carrito: congela precios, reserva stock (lotes que caducan primero) y
    genera los pagos de anticipo y saldo. El pedido nace PENDIENTE."""
    return pedidos_service.crear(db, id_cliente, data)


@router.get("/mis-pedidos", response_model=MisPedidosPage)
@limiter.limit("60/minute")
def mis_pedidos(
    request: Request,
    tab: TabPedidos = Query(default="activos", description="activos | entregados | cancelados"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    id_cliente: uuid.UUID = Depends(require_cliente),
):
    return pedidos_service.listar_cliente(db, id_cliente, tab, page, page_size)


@router.get("/pedidos/{id_pedido}", response_model=PedidoOut)
@limiter.limit("60/minute")
def detalle_pedido(
    request: Request,
    id_pedido: uuid.UUID,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Lo ve el cliente dueño del pedido o el distribuidor al que se le pidió."""
    return pedidos_service.obtener(db, user, id_pedido)


@router.post("/pedidos/{id_pedido}/cancelar", response_model=PedidoOut)
@limiter.limit("20/minute")
def cancelar_pedido(
    request: Request,
    id_pedido: uuid.UUID,
    data: CancelarIn | None = None,
    db: Session = Depends(get_db),
    id_cliente: uuid.UUID = Depends(require_cliente),
):
    """Cancela mientras el pedido no vaya en ruta. Devuelve el stock a sus lotes."""
    return pedidos_service.cancelar_cliente(
        db, id_cliente, id_pedido, data.motivo if data else None
    )
