import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import require_distribuidor
from app.core.database import get_db
from app.core.limiter import limiter
from app.schemas.pedido import PedidoOut
from app.schemas.pedido_distribuidor import (
    CancelarProveedorIn,
    PedidoManualIn,
    PedidosDistribuidorPage,
    TabPedidosDistribuidor,
)
from app.services import pedidos_distribuidor as pedidos_service

router = APIRouter(tags=["pedidos"])


@router.get("/pedidos", response_model=PedidosDistribuidorPage)
@limiter.limit("60/minute")
def pedidos_en_curso(
    request: Request,
    tab: TabPedidosDistribuidor = Query(
        default="todos",
        description="todos | pendiente (aún no sale a ruta) | en_envio | entregado | cancelado",
    ),
    q: str | None = Query(
        default=None, max_length=100, description="Folio, cafetería o dirección de entrega"
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    id_distribuidor: uuid.UUID = Depends(require_distribuidor),
):
    """Pantalla 'Pedidos en curso'. `resumen` alimenta las tarjetas de arriba (siempre
    globales) y `conteos` las pestañas (respetan la búsqueda). Cada pedido trae `acciones`
    para habilitar los botones."""
    return pedidos_service.listar(db, id_distribuidor, tab, q, page, page_size)


@router.post("/pedidos/manual", response_model=PedidoOut, status_code=201)
@limiter.limit("20/minute")
def generar_orden_manual(
    request: Request,
    data: PedidoManualIn,
    db: Session = Depends(get_db),
    id_distribuidor: uuid.UUID = Depends(require_distribuidor),
):
    """'Generar orden manual': pedido a nombre de un cliente ya registrado (se identifica por
    su correo). Nace PENDIENTE y reserva el stock igual que uno hecho por el cliente."""
    return pedidos_service.crear_manual(db, id_distribuidor, data)


@router.post("/pedidos/{id_pedido}/completar-armado", response_model=PedidoOut)
@limiter.limit("30/minute")
def completar_armado(
    request: Request,
    id_pedido: uuid.UUID,
    db: Session = Depends(get_db),
    id_distribuidor: uuid.UUID = Depends(require_distribuidor),
):
    """'Completar armado': el pedido pasa de EN_PROCESO a EN_ENVIO (ya no se puede cancelar)."""
    return pedidos_service.completar_armado(db, id_distribuidor, id_pedido)


@router.post("/pedidos/{id_pedido}/confirmar-entrega", response_model=PedidoOut)
@limiter.limit("30/minute")
def confirmar_entrega(
    request: Request,
    id_pedido: uuid.UUID,
    db: Session = Depends(get_db),
    id_distribuidor: uuid.UUID = Depends(require_distribuidor),
):
    """'Confirmar entrega en sucursal': EN_ENVIO pasa a ENTREGADO y se guarda la fecha real."""
    return pedidos_service.confirmar_entrega(db, id_distribuidor, id_pedido)


@router.post("/pedidos/{id_pedido}/cancelar-proveedor", response_model=PedidoOut)
@limiter.limit("20/minute")
def cancelar_pedido_proveedor(
    request: Request,
    id_pedido: uuid.UUID,
    data: CancelarProveedorIn,
    db: Session = Depends(get_db),
    id_distribuidor: uuid.UUID = Depends(require_distribuidor),
):
    """Cancela con motivo obligatorio mientras no vaya en ruta. Devuelve el stock a sus lotes."""
    return pedidos_service.cancelar_proveedor(db, id_distribuidor, id_pedido, data.motivo)
