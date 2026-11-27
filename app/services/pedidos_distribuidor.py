import uuid
from datetime import datetime, timezone
from typing import NoReturn

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import Conflicto, NoEncontrado
from app.models import Cliente, Pedido
from app.schemas.pago import LiquidacionIn
from app.schemas.pedido import PedidoCreate, PedidoOut
from app.schemas.pedido_distribuidor import (
    ConteosPedidosDistribuidor,
    PedidoManualCobroUnicoIn,
    PedidoManualIn,
    PedidosDistribuidorPage,
    TabPedidosDistribuidor,
)
from app.services import pedidos as base

TABS: dict[str, tuple[str, ...]] = {
    "pendiente": ("PENDIENTE", "POR_VALIDAR", "EN_PROCESO"),
    "en_envio": ("EN_ENVIO",),
    "entregado": ("ENTREGADO",),
    "cancelado": ("CANCELADO",),
}

_SIN_ANTICIPO = "El pedido todavía no tiene el anticipo confirmado"


# ---------------------------------------------------------------- helpers internos


def _conflicto(db: Session, mensaje: str) -> NoReturn:
    db.rollback()  # suelta los bloqueos antes de responder
    raise Conflicto(mensaje)


def _pedido_bloqueado(db: Session, id_distribuidor: uuid.UUID, id_pedido: uuid.UUID) -> Pedido:
    pedido = db.scalar(
        select(Pedido)
        .where(Pedido.id_pedido == id_pedido, Pedido.distribuidor_id == id_distribuidor)
        .with_for_update()
    )
    if pedido is None:
        db.rollback()
        raise NoEncontrado("Pedido no encontrado")  # no revela pedidos de otros distribuidores
    return pedido


def _guardar(db: Session, pedido: Pedido, error: str) -> PedidoOut:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflicto(error)
    db.refresh(pedido)
    return base._armar(db, [pedido])[0]


def _grupos(por_estatus: dict[str, int]) -> ConteosPedidosDistribuidor:
    def n(*estatus: str) -> int:
        return sum(por_estatus.get(e, 0) for e in estatus)

    return ConteosPedidosDistribuidor(
        todos=sum(por_estatus.values()),
        pendiente=n(*TABS["pendiente"]),
        en_envio=n(*TABS["en_envio"]),
        entregado=n(*TABS["entregado"]),
        cancelado=n(*TABS["cancelado"]),
    )


def _busqueda(q: str | None) -> list:
    if not q or not q.strip():
        return []
    t = q.strip()
    folio = t.lower().removeprefix("#").removeprefix("ped-")
    return [
        or_(
            cast(Pedido.id_pedido, String).istartswith(folio, autoescape=True),
            Cliente.nombre.icontains(t, autoescape=True),
            Pedido.direccion_entrega.icontains(t, autoescape=True),
        )
    ]


# ---------------------------------------------------------------- casos de uso


def listar(
    db: Session,
    id_distribuidor: uuid.UUID,
    tab: TabPedidosDistribuidor,
    q: str | None,
    page: int,
    page_size: int,
) -> PedidosDistribuidorPage:
    suyo = Pedido.distribuidor_id == id_distribuidor
    busqueda = _busqueda(q)

    def contar(*filtros) -> dict[str, int]:
        return dict(
            db.execute(
                select(Pedido.estatus, func.count())
                .select_from(Pedido)
                .join(Cliente, Cliente.id_cliente == Pedido.cliente_id)
                .where(suyo, *filtros)
                .group_by(Pedido.estatus)
            ).all()
        )

    resumen = _grupos(contar())
    conteos = _grupos(contar(*busqueda)) if busqueda else resumen

    stmt = (
        select(Pedido)
        .join(Cliente, Cliente.id_cliente == Pedido.cliente_id)
        .where(suyo, *busqueda)
    )
    if tab != "todos":
        stmt = stmt.where(Pedido.estatus.in_(TABS[tab]))
    pedidos = db.scalars(
        stmt.order_by(Pedido.fecha_realizacion.desc(), Pedido.id_pedido)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    total = getattr(conteos, tab)
    return PedidosDistribuidorPage(
        pedidos=base._armar(db, list(pedidos)),
        conteos=conteos,
        resumen=resumen,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=(total + page_size - 1) // page_size if total else 0,
    )


def completar_armado(
    db: Session, id_distribuidor: uuid.UUID, id_pedido: uuid.UUID
) -> PedidoOut:
    """EN_PROCESO -> EN_ENVIO: el pedido sale a ruta y ya no se puede cancelar."""
    pedido = _pedido_bloqueado(db, id_distribuidor, id_pedido)
    if pedido.estatus != "EN_PROCESO":
        _conflicto(
            db,
            {
                "PENDIENTE": _SIN_ANTICIPO,
                "POR_VALIDAR": _SIN_ANTICIPO,
                "EN_ENVIO": "El pedido ya va en ruta",
                "ENTREGADO": "El pedido ya fue entregado",
                "CANCELADO": "El pedido está cancelado",
            }.get(pedido.estatus, "El pedido no está en preparación"),
        )
    pedido.estatus = "EN_ENVIO"
    return _guardar(db, pedido, "No se pudo completar el armado")


def confirmar_entrega(
    db: Session, id_distribuidor: uuid.UUID, id_pedido: uuid.UUID
) -> PedidoOut:
    """EN_ENVIO -> ENTREGADO, o EN_PROCESO -> ENTREGADO ('entrega en mostrador': la
    cafetería pasa a recoger y no hay ruta). No exige que el saldo esté cobrado: la
    liquidación se registra aparte y el pedido queda con estado_cobro PENDIENTE_LIQUIDAR."""
    pedido = _pedido_bloqueado(db, id_distribuidor, id_pedido)
    if pedido.estatus not in ("EN_PROCESO", "EN_ENVIO"):
        _conflicto(
            db,
            {
                "PENDIENTE": _SIN_ANTICIPO,
                "POR_VALIDAR": _SIN_ANTICIPO,
                "ENTREGADO": "El pedido ya fue entregado",
                "CANCELADO": "El pedido está cancelado",
            }.get(pedido.estatus, "El pedido no está listo para entregarse"),
        )
    pedido.estatus = "ENTREGADO"
    pedido.fecha_entrega_real = datetime.now(timezone.utc)
    return _guardar(db, pedido, "No se pudo confirmar la entrega")


def cancelar_proveedor(
    db: Session, id_distribuidor: uuid.UUID, id_pedido: uuid.UUID, motivo: str
) -> PedidoOut:
    """Cancela con motivo hasta que el pedido sale a ruta. Devuelve el stock; si el anticipo
    ya estaba confirmado queda reembolso_pendiente."""
    pedido = _pedido_bloqueado(db, id_distribuidor, id_pedido)
    if pedido.estatus not in base.CANCELABLES_PROVEEDOR:
        _conflicto(
            db,
            {
                "EN_ENVIO": "El pedido ya va en ruta y no admite cancelación",
                "ENTREGADO": "El pedido ya fue entregado",
                "CANCELADO": "El pedido ya está cancelado",
            }.get(pedido.estatus, "El pedido no se puede cancelar en este estado"),
        )
    return base._cancelar(db, pedido, "PROVEEDOR", motivo)


def crear_manual(db: Session, id_distribuidor: uuid.UUID, data: PedidoManualIn) -> PedidoOut:
    """Mismo proceso que un pedido del cliente (reserva de stock, anticipo y saldo), pero a
    nombre del cliente indicado. El cliente verá el pedido en 'Mis pedidos'."""
    cliente = db.scalar(select(Cliente).where(Cliente.correo == data.correo_cliente))
    if cliente is None:
        raise NoEncontrado("No hay un cliente registrado con ese correo")
    return base.crear(
        db,
        cliente.id_cliente,
        PedidoCreate(
            id_distribuidor=id_distribuidor,
            direccion_entrega=data.direccion_entrega,
            items=data.items,
        ),
    )


def crear_manual_cobro_unico(
    db: Session, id_distribuidor: uuid.UUID, data: PedidoManualCobroUnicoIn
) -> PedidoOut:
    """Venta directa: reserva el stock como cualquier pedido, pero sin anticipo ni saldo. Se
    registra un solo pago por el total y el pedido nace ENTREGADO, sin pasar por preparación
    ni envío. El cliente debe estar registrado."""
    cliente = db.scalar(select(Cliente).where(Cliente.correo == data.correo_cliente))
    if cliente is None:
        raise NoEncontrado("No hay un cliente registrado con ese correo")
    return base.crear(
        db,
        cliente.id_cliente,
        PedidoCreate(
            id_distribuidor=id_distribuidor,
            direccion_entrega=data.direccion_entrega,
            items=data.items,
        ),
        cobro_unico=LiquidacionIn(metodo=data.metodo, comprobante_url=data.comprobante_url),
    )
