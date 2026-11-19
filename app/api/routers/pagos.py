import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import require_cliente, require_distribuidor
from app.core.database import get_db
from app.core.limiter import limiter
from app.schemas.pago import (
    CobranzaPage,
    ComprobanteIn,
    LiquidacionIn,
    RechazarIn,
    TabCobranza,
    ValidarAnticipoIn,
)
from app.schemas.pedido import PedidoOut
from app.services import pagos as pagos_service

router = APIRouter(tags=["pagos"])


# ------------------------------------------------------------ cliente


@router.post("/pedidos/{id_pedido}/anticipo/comprobante", response_model=PedidoOut)
@limiter.limit("20/minute")
def subir_comprobante(
    request: Request,
    id_pedido: uuid.UUID,
    data: ComprobanteIn,
    db: Session = Depends(get_db),
    id_cliente: uuid.UUID = Depends(require_cliente),
):
    """El cliente avisa que ya transfirió el anticipo (enlace https a imagen o PDF).
    El pedido pasa a POR_VALIDAR. También sirve para reenviar tras un rechazo."""
    return pagos_service.subir_comprobante_anticipo(db, id_cliente, id_pedido, data.comprobante_url)


# ------------------------------------------------------------ distribuidor


@router.post("/pedidos/{id_pedido}/anticipo/validar", response_model=PedidoOut)
@limiter.limit("30/minute")
def validar_anticipo(
    request: Request,
    id_pedido: uuid.UUID,
    data: ValidarAnticipoIn,
    db: Session = Depends(get_db),
    id_distribuidor: uuid.UUID = Depends(require_distribuidor),
):
    """Confirma el anticipo y fija la fecha de entrega. El pedido pasa a EN_PROCESO."""
    return pagos_service.validar_anticipo(
        db, id_distribuidor, id_pedido, data.fecha_entrega_estimada
    )


@router.post("/pedidos/{id_pedido}/anticipo/rechazar", response_model=PedidoOut)
@limiter.limit("30/minute")
def rechazar_anticipo(
    request: Request,
    id_pedido: uuid.UUID,
    data: RechazarIn,
    db: Session = Depends(get_db),
    id_distribuidor: uuid.UUID = Depends(require_distribuidor),
):
    """Rechaza el comprobante con un motivo. El pedido vuelve a PENDIENTE."""
    return pagos_service.rechazar_anticipo(db, id_distribuidor, id_pedido, data.motivo)


@router.post("/pedidos/{id_pedido}/liquidacion", response_model=PedidoOut)
@limiter.limit("30/minute")
def registrar_liquidacion(
    request: Request,
    id_pedido: uuid.UUID,
    data: LiquidacionIn,
    db: Session = Depends(get_db),
    id_distribuidor: uuid.UUID = Depends(require_distribuidor),
):
    """'Registrar Liquidación Final': cobra el saldo en efectivo o por transferencia."""
    return pagos_service.registrar_liquidacion(db, id_distribuidor, id_pedido, data)


@router.post("/pedidos/{id_pedido}/reembolso", response_model=PedidoOut)
@limiter.limit("30/minute")
def registrar_reembolso(
    request: Request,
    id_pedido: uuid.UUID,
    data: ComprobanteIn,
    db: Session = Depends(get_db),
    id_distribuidor: uuid.UUID = Depends(require_distribuidor),
):
    """Registra la devolución del anticipo de un pedido cancelado (comprobante del reembolso)."""
    return pagos_service.registrar_reembolso(db, id_distribuidor, id_pedido, data.comprobante_url)


@router.get("/cobranza", response_model=CobranzaPage)
@limiter.limit("60/minute")
def cobranza(
    request: Request,
    tab: TabCobranza = Query(
        default="todos",
        description="todos | anticipos_por_confirmar | pendiente_liquidar | pagados | reembolsos",
    ),
    q: str | None = Query(
        default=None, max_length=100, description="Folio, cafetería o referencia bancaria"
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    id_distribuidor: uuid.UUID = Depends(require_distribuidor),
):
    return pagos_service.cobranza(db, id_distribuidor, tab, q, page, page_size)
