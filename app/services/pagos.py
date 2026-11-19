import uuid
from datetime import datetime, timedelta, timezone
from typing import NoReturn

from sqlalchemy import Numeric, String, and_, cast, exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import Conflicto, NoEncontrado
from app.models import Cliente, DetallePedido, Pago, Pedido
from app.schemas.pago import (
    CobranzaPage,
    ConteosCobranza,
    LiquidacionIn,
    ResumenCobranza,
    TabCobranza,
)
from app.schemas.pedido import PedidoOut
from app.services.pedidos import _armar


# ---------------------------------------------------------------- helpers internos


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _dinero(x) -> float:
    return round(float(x or 0), 2)


def _conflicto(db: Session, mensaje: str) -> NoReturn:
    db.rollback()  # suelta los bloqueos antes de responder
    raise Conflicto(mensaje)


def _pedido_bloqueado(
    db: Session,
    id_pedido: uuid.UUID,
    *,
    cliente_id: uuid.UUID | None = None,
    distribuidor_id: uuid.UUID | None = None,
) -> Pedido:
    """Pedido del dueño indicado, bloqueado para que dos acciones no se pisen.
    Si no es suyo responde 404 (no revela pedidos ajenos)."""
    stmt = select(Pedido).where(Pedido.id_pedido == id_pedido)
    if cliente_id is not None:
        stmt = stmt.where(Pedido.cliente_id == cliente_id)
    if distribuidor_id is not None:
        stmt = stmt.where(Pedido.distribuidor_id == distribuidor_id)
    pedido = db.scalar(stmt.with_for_update())
    if pedido is None:
        db.rollback()
        raise NoEncontrado("Pedido no encontrado")
    return pedido


def _pago(db: Session, id_pedido: uuid.UUID, tipo: str) -> Pago | None:
    return db.scalar(
        select(Pago).where(Pago.pedido_id == id_pedido, Pago.tipo == tipo).with_for_update()
    )


def _guardar(db: Session, pedido: Pedido, error: str) -> PedidoOut:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflicto(error)
    db.refresh(pedido)
    return _armar(db, [pedido])[0]


# ---------------------------------------------------------------- acciones del cliente


def subir_comprobante_anticipo(
    db: Session, id_cliente: uuid.UUID, id_pedido: uuid.UUID, url: str
) -> PedidoOut:
    """PENDIENTE -> POR_VALIDAR. También sirve para volver a enviar tras un rechazo."""
    pedido = _pedido_bloqueado(db, id_pedido, cliente_id=id_cliente)
    if pedido.estatus != "PENDIENTE":
        _conflicto(
            db,
            {
                "POR_VALIDAR": "Ya enviaste un comprobante; espera a que el proveedor lo valide",
                "CANCELADO": "El pedido está cancelado",
            }.get(pedido.estatus, "El anticipo de este pedido ya fue confirmado"),
        )
    pago = _pago(db, id_pedido, "ANTICIPO")
    if pago is None or pago.estado not in ("PENDIENTE", "RECHAZADO"):
        _conflicto(db, "El anticipo de este pedido no admite comprobante")

    pago.comprobante_url = url
    pago.estado = "POR_VALIDAR"
    pago.motivo_rechazo = None
    pago.fecha_comprobante = _ahora()
    pago.fecha_validacion = None
    pedido.estatus = "POR_VALIDAR"
    return _guardar(db, pedido, "No se pudo registrar el comprobante")


# ---------------------------------------------------------------- acciones del distribuidor


def validar_anticipo(
    db: Session, id_distribuidor: uuid.UUID, id_pedido: uuid.UUID, fecha_entrega: datetime
) -> PedidoOut:
    """POR_VALIDAR -> EN_PROCESO, fijando la fecha estimada de entrega."""
    pedido = _pedido_bloqueado(db, id_pedido, distribuidor_id=id_distribuidor)
    pago = _pago(db, id_pedido, "ANTICIPO")
    if pedido.estatus != "POR_VALIDAR" or pago is None or pago.estado != "POR_VALIDAR":
        _conflicto(db, "Este pedido no tiene un anticipo esperando validación")

    pago.estado = "CONFIRMADO"
    pago.fecha_validacion = _ahora()
    pedido.estatus = "EN_PROCESO"
    pedido.fecha_entrega_estimada = fecha_entrega
    return _guardar(db, pedido, "No se pudo validar el anticipo")


def rechazar_anticipo(
    db: Session, id_distribuidor: uuid.UUID, id_pedido: uuid.UUID, motivo: str
) -> PedidoOut:
    """POR_VALIDAR -> PENDIENTE: el cliente puede mandar otro comprobante."""
    pedido = _pedido_bloqueado(db, id_pedido, distribuidor_id=id_distribuidor)
    pago = _pago(db, id_pedido, "ANTICIPO")
    if pedido.estatus != "POR_VALIDAR" or pago is None or pago.estado != "POR_VALIDAR":
        _conflicto(db, "Este pedido no tiene un anticipo esperando validación")

    pago.estado = "RECHAZADO"
    pago.motivo_rechazo = motivo
    pago.fecha_validacion = _ahora()
    pedido.estatus = "PENDIENTE"
    return _guardar(db, pedido, "No se pudo rechazar el anticipo")


def registrar_liquidacion(
    db: Session, id_distribuidor: uuid.UUID, id_pedido: uuid.UUID, data: LiquidacionIn
) -> PedidoOut:
    """Cobra el saldo contra entrega. No cambia el estatus del pedido (eso es 'confirmar
    entrega'); se puede registrar con el pedido en ruta o ya entregado."""
    pedido = _pedido_bloqueado(db, id_pedido, distribuidor_id=id_distribuidor)
    if pedido.estatus not in ("EN_ENVIO", "ENTREGADO"):
        _conflicto(db, "El saldo se cobra cuando el pedido va en ruta o ya fue entregado")
    anticipo = _pago(db, id_pedido, "ANTICIPO")
    if anticipo is None or anticipo.estado != "CONFIRMADO":
        _conflicto(db, "El anticipo de este pedido no está confirmado")
    final = _pago(db, id_pedido, "FINAL")
    if final is None or final.estado == "CONFIRMADO":
        _conflicto(db, "Este pedido ya está liquidado: no hay saldo pendiente")

    ahora = _ahora()
    final.metodo = data.metodo
    final.comprobante_url = data.comprobante_url
    final.fecha_comprobante = ahora if data.comprobante_url else None
    final.estado = "CONFIRMADO"
    final.fecha_validacion = ahora
    return _guardar(db, pedido, "No se pudo registrar la liquidación")


def registrar_reembolso(
    db: Session, id_distribuidor: uuid.UUID, id_pedido: uuid.UUID, url: str
) -> PedidoOut:
    """Cierra un pedido cancelado devolviendo el anticipo que ya se había confirmado."""
    pedido = _pedido_bloqueado(db, id_pedido, distribuidor_id=id_distribuidor)
    anticipo = _pago(db, id_pedido, "ANTICIPO")
    if pedido.estatus != "CANCELADO" or anticipo is None or anticipo.estado != "CONFIRMADO":
        _conflicto(db, "Este pedido no tiene un anticipo por reembolsar")
    if anticipo.fecha_reembolso is not None:
        _conflicto(db, "El reembolso de este pedido ya se registró")

    anticipo.comprobante_reembolso_url = url
    anticipo.fecha_reembolso = _ahora()
    return _guardar(db, pedido, "No se pudo registrar el reembolso")


# ---------------------------------------------------------------- cobranza


def _subconsultas():
    def de_anticipo(col):
        return (
            select(col)
            .where(Pago.pedido_id == Pedido.id_pedido, Pago.tipo == "ANTICIPO")
            .correlate(Pedido)
            .scalar_subquery()
        )

    ant_estado = de_anticipo(Pago.estado)
    ant_reembolso = de_anticipo(Pago.fecha_reembolso)
    fin_estado = (
        select(Pago.estado)
        .where(Pago.pedido_id == Pedido.id_pedido, Pago.tipo == "FINAL")
        .correlate(Pedido)
        .scalar_subquery()
    )
    return ant_estado, ant_reembolso, fin_estado


def _condiciones_tabs() -> dict:
    ant, ant_reemb, fin = _subconsultas()
    activo = Pedido.estatus != "CANCELADO"
    return {
        "anticipos_por_confirmar": and_(activo, ant == "POR_VALIDAR"),
        "pendiente_liquidar": and_(
            activo, ant == "CONFIRMADO", fin.is_not(None), fin != "CONFIRMADO"
        ),
        "pagados": and_(activo, ant == "CONFIRMADO", or_(fin.is_(None), fin == "CONFIRMADO")),
        "reembolsos": and_(Pedido.estatus == "CANCELADO", ant == "CONFIRMADO", ant_reemb.is_(None)),
        # todo lo vivo, más lo cancelado que movió dinero; los cancelados sin cobros no estorban
        "todos": or_(activo, ant == "CONFIRMADO"),
    }


def _busqueda(q: str | None) -> list:
    if not q or not q.strip():
        return []
    t = q.strip()
    folio = t.lower().removeprefix("#").removeprefix("ped-").removeprefix("sfy-")
    return [
        or_(
            cast(Pedido.id_pedido, String).istartswith(folio, autoescape=True),
            Cliente.nombre.icontains(t, autoescape=True),
            exists().where(
                Pago.pedido_id == Pedido.id_pedido, Pago.referencia.icontains(t, autoescape=True)
            ),
        )
    ]


def cobranza(
    db: Session,
    id_distribuidor: uuid.UUID,
    tab: TabCobranza,
    q: str | None,
    page: int,
    page_size: int,
) -> CobranzaPage:
    suyo = Pedido.distribuidor_id == id_distribuidor
    busqueda = _busqueda(q)
    tabs = _condiciones_tabs()

    def contar(cond) -> int:
        return (
            db.scalar(
                select(func.count())
                .select_from(Pedido)
                .join(Cliente, Cliente.id_cliente == Pedido.cliente_id)
                .where(suyo, *busqueda, cond)
            )
            or 0
        )

    conteos = ConteosCobranza(**{nombre: contar(cond) for nombre, cond in tabs.items()})
    total = getattr(conteos, tab)

    pedidos = db.scalars(
        select(Pedido)
        .join(Cliente, Cliente.id_cliente == Pedido.cliente_id)
        .where(suyo, *busqueda, tabs[tab])
        .order_by(Pedido.fecha_realizacion.desc(), Pedido.id_pedido)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    return CobranzaPage(
        pedidos=_armar(db, list(pedidos)),
        conteos=conteos,
        resumen=_resumen(db, id_distribuidor),
        page=page,
        page_size=page_size,
        total=total,
        total_pages=(total + page_size - 1) // page_size if total else 0,
    )


def _resumen(db: Session, id_distribuidor: uuid.UUID) -> ResumenCobranza:
    # REAL -> NUMERIC antes de sumar: así no se acumula error de punto flotante
    monto = cast(Pago.monto, Numeric(12, 2))
    linea = cast(DetallePedido.precio_unitario, Numeric(12, 2)) * DetallePedido.cantidad
    suyo = Pedido.distribuidor_id == id_distribuidor
    vivo = Pedido.estatus != "CANCELADO"
    desde = (datetime.now(timezone.utc) - timedelta(days=7)).replace(tzinfo=None)
    ant, _reemb, _fin = _subconsultas()

    total_vendido = db.scalar(
        select(func.sum(linea))
        .select_from(DetallePedido)
        .join(Pedido, Pedido.id_pedido == DetallePedido.pedido_id)
        .where(suyo, vivo, Pedido.fecha_realizacion >= desde)
    )
    anticipos = db.scalar(
        select(func.sum(monto))
        .select_from(Pago)
        .join(Pedido, Pedido.id_pedido == Pago.pedido_id)
        .where(
            suyo,
            vivo,
            Pedido.fecha_realizacion >= desde,
            Pago.tipo == "ANTICIPO",
            Pago.estado == "CONFIRMADO",
        )
    )
    saldos = db.scalar(
        select(func.sum(monto))
        .select_from(Pago)
        .join(Pedido, Pedido.id_pedido == Pago.pedido_id)
        .where(
            suyo,
            vivo,
            ant == "CONFIRMADO",
            Pago.tipo == "FINAL",
            Pago.estado.not_in(("CONFIRMADO", "ANULADO")),
        )
    )
    local = timezone(timedelta(hours=settings.zona_horaria_horas))
    inicio_dia = datetime.now(local).replace(hour=0, minute=0, second=0, microsecond=0)
    hoy = db.scalar(
        select(func.sum(monto))
        .select_from(Pago)
        .join(Pedido, Pedido.id_pedido == Pago.pedido_id)
        .where(
            suyo,
            Pago.tipo == "FINAL",
            Pago.estado == "CONFIRMADO",
            Pago.fecha_validacion >= inicio_dia,
            Pago.fecha_validacion < inicio_dia + timedelta(days=1),
        )
    )
    return ResumenCobranza(
        total_vendido_semana=_dinero(total_vendido),
        anticipos_cobrados=_dinero(anticipos),
        saldos_pendientes=_dinero(saldos),
        liquidaciones_hoy=_dinero(hoy),
    )
