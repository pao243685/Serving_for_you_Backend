import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import AppError, Conflicto, NoAutenticado, NoEncontrado
from app.models import (
    Cliente,
    DetallePedido,
    DetallePedidoLote,
    Distribuidor,
    Pago,
    Pedido,
    Producto,
    ProductoStock,
    Stock,
)
from app.schemas.pago import LiquidacionIn
from app.schemas.pedido import (
    AccionesPedido,
    ClienteDePedido,
    ConteosPedidos,
    DistribuidorDePedido,
    LineaPedido,
    MisPedidosPage,
    PagoOut,
    PedidoCreate,
    PedidoOut,
    ResumenMisPedidos,
    TabPedidos,
)

TABS: dict[str, tuple[str, ...]] = {
    "activos": ("PENDIENTE", "POR_VALIDAR", "EN_PROCESO", "EN_ENVIO"),
    "entregados": ("ENTREGADO",),
    "cancelados": ("CANCELADO",),
}
# El cliente puede cancelar hasta que el pedido sale a ruta
CANCELABLES_CLIENTE = ("PENDIENTE", "POR_VALIDAR", "EN_PROCESO")
# El proveedor también puede cancelar hasta que el pedido sale a ruta
CANCELABLES_PROVEEDOR = ("PENDIENTE", "POR_VALIDAR", "EN_PROCESO")
PASO = {"PENDIENTE": 1, "POR_VALIDAR": 1, "EN_PROCESO": 2, "EN_ENVIO": 3, "ENTREGADO": 4}


# ---------------------------------------------------------------- helpers internos


def _ahora_utc() -> datetime:
    return datetime.now(timezone.utc)


def _utc(dt: datetime | None) -> datetime | None:
    """Las columnas TIMESTAMP sin zona se guardan en UTC; se devuelven con zona explícita."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _dinero(x: float) -> float:
    return round(float(x), 2)


def folio_pedido(id_pedido: uuid.UUID) -> str:
    """Folio corto para mostrar (PED-1A2B3C4D). Se deriva del id; no se guarda."""
    return f"PED-{id_pedido.hex[:8].upper()}"


def _referencia(id_pedido: uuid.UUID, tipo: str) -> str:
    # Concepto que el cliente pone en la transferencia (la columna admite 20 caracteres)
    return f"SFY-{id_pedido.hex[:8].upper()}-{'A' if tipo == 'ANTICIPO' else 'F'}"


def _acciones(pedido: Pedido, anticipo: Pago | None, final: Pago | None) -> AccionesPedido:
    """Qué se puede hacer con el pedido en su estado actual (lo ejecuta el rol que toca)."""
    est = pedido.estatus
    ant = anticipo.estado if anticipo is not None else None
    anticipo_ok = ant == "CONFIRMADO"
    return AccionesPedido(
        subir_comprobante=est == "PENDIENTE" and ant in ("PENDIENTE", "RECHAZADO"),
        cancelar_cliente=est in CANCELABLES_CLIENTE,
        validar_anticipo=est == "POR_VALIDAR" and ant == "POR_VALIDAR",
        rechazar_anticipo=est == "POR_VALIDAR" and ant == "POR_VALIDAR",
        completar_armado=est == "EN_PROCESO",
        confirmar_entrega=est in ("EN_PROCESO", "EN_ENVIO"),
        cancelar_proveedor=est in CANCELABLES_PROVEEDOR,
        registrar_liquidacion=(
            est in ("EN_PROCESO", "EN_ENVIO", "ENTREGADO")
            and anticipo_ok
            and final is not None
            and final.estado not in ("CONFIRMADO", "ANULADO")
        ),
        registrar_reembolso=(
            est == "CANCELADO" and anticipo_ok and anticipo.fecha_reembolso is None
        ),
    )


def _estado_cobro(pedido: Pedido, anticipo: Pago | None, final: Pago | None) -> str:
    confirmado = anticipo is not None and anticipo.estado == "CONFIRMADO"
    if pedido.estatus == "CANCELADO":
        if not confirmado:
            return "SIN_COBROS"
        return "REEMBOLSADO" if anticipo.fecha_reembolso is not None else "REEMBOLSO_PENDIENTE"
    if anticipo is None and final is not None and final.estado == "CONFIRMADO":
        return "PAGADO"  # cobro único: se pagó todo de una vez, sin anticipo
    if anticipo is None or anticipo.estado in ("PENDIENTE", "RECHAZADO"):
        return "ANTICIPO_PENDIENTE"
    if anticipo.estado == "POR_VALIDAR":
        return "ANTICIPO_POR_CONFIRMAR"
    if final is None or final.estado == "CONFIRMADO":
        return "PAGADO"
    return "PENDIENTE_LIQUIDAR"


def _armar(db: Session, pedidos: list[Pedido]) -> list[PedidoOut]:
    """Convierte pedidos en respuestas completas con 4 consultas, sin importar cuántos sean."""
    if not pedidos:
        return []
    ids = [p.id_pedido for p in pedidos]

    lineas: dict[uuid.UUID, list[LineaPedido]] = {i: [] for i in ids}
    filas = db.execute(
        select(DetallePedido, Producto)
        .join(Producto, Producto.id_producto == DetallePedido.producto_id)
        .where(DetallePedido.pedido_id.in_(ids))
        .order_by(Producto.nombre, Producto.id_producto)
    ).all()
    for d, prod in filas:
        precio = _dinero(d.precio_unitario)
        lineas[d.pedido_id].append(
            LineaPedido(
                id_producto=prod.id_producto,
                nombre=prod.nombre,
                descripcion_producto=prod.descripcion_producto,
                tamano=prod.tamano,
                unidad_medida=prod.unidad_medida,
                imagen_url=prod.imagen_url,
                cantidad=d.cantidad,
                precio_unitario=precio,
                subtotal=_dinero(d.cantidad * precio),
            )
        )

    pagos: dict[uuid.UUID, list[Pago]] = {i: [] for i in ids}
    for pago in db.scalars(select(Pago).where(Pago.pedido_id.in_(ids)).order_by(Pago.tipo)):
        pagos[pago.pedido_id].append(pago)  # ANTICIPO antes que FINAL

    dists = {
        d.id_distribuidor: d
        for d in db.scalars(
            select(Distribuidor).where(
                Distribuidor.id_distribuidor.in_({p.distribuidor_id for p in pedidos})
            )
        )
    }
    clientes = {
        c.id_cliente: c
        for c in db.scalars(
            select(Cliente).where(Cliente.id_cliente.in_({p.cliente_id for p in pedidos}))
        )
    }

    salida = []
    for p in pedidos:
        d, c = dists[p.distribuidor_id], clientes[p.cliente_id]
        ls = lineas[p.id_pedido]
        ps = pagos[p.id_pedido]
        anticipo = next((x for x in ps if x.tipo == "ANTICIPO"), None)
        final = next((x for x in ps if x.tipo == "FINAL"), None)
        anticipo_ok = anticipo is not None and anticipo.estado == "CONFIRMADO"
        saldo = (
            final.monto
            if final is not None and final.estado not in ("CONFIRMADO", "ANULADO")
            and p.estatus != "CANCELADO"
            else 0
        )
        salida.append(
            PedidoOut(
                id_pedido=p.id_pedido,
                folio=folio_pedido(p.id_pedido),
                estatus=p.estatus,
                paso=PASO.get(p.estatus),
                cliente=ClienteDePedido(
                    id_cliente=c.id_cliente, nombre=c.nombre, telefono=c.telefono
                ),
                distribuidor=DistribuidorDePedido(
                    id_distribuidor=d.id_distribuidor,
                    nombre_marca=d.nombre_marca,
                    telefono=d.telefono,
                    banco=d.banco,
                    titular=d.titular,
                    clabe=d.clabe,
                ),
                direccion_entrega=p.direccion_entrega,
                fecha_realizacion=_utc(p.fecha_realizacion),
                fecha_entrega_estimada=_utc(p.fecha_entrega_estimada),
                fecha_entrega_real=_utc(p.fecha_entrega_real),
                fecha_cancelacion=_utc(p.fecha_cancelacion),
                cancelado_por=p.cancelado_por,
                motivo_cancelacion=p.motivo_cancelacion,
                lineas=ls,
                total_unidades=sum(x.cantidad for x in ls),
                total_productos=_dinero(sum(x.subtotal for x in ls)),
                pagos=[
                    PagoOut(
                        id_pago=x.id_pago,
                        tipo=x.tipo,
                        monto=_dinero(x.monto),
                        estado=x.estado,
                        metodo=x.metodo,
                        referencia=x.referencia,
                        comprobante_url=x.comprobante_url,
                        motivo_rechazo=x.motivo_rechazo,
                        fecha_creacion=_utc(x.fecha_creacion),
                        fecha_comprobante=_utc(x.fecha_comprobante),
                        fecha_validacion=_utc(x.fecha_validacion),
                        fecha_reembolso=_utc(x.fecha_reembolso),
                        comprobante_reembolso_url=x.comprobante_reembolso_url,
                    )
                    for x in ps
                ],
                anticipo_pagado=anticipo_ok,
                saldo_restante=_dinero(saldo),
                cancelable_por_cliente=p.estatus in CANCELABLES_CLIENTE,
                reembolso_pendiente=(
                    p.estatus == "CANCELADO"
                    and anticipo_ok
                    and anticipo.fecha_reembolso is None
                ),
                monto_cobrado=_dinero(sum(x.monto for x in ps if x.estado == "CONFIRMADO")),
                estado_cobro=_estado_cobro(p, anticipo, final),
                acciones=_acciones(p, anticipo, final),
            )
        )
    return salida


# ---------------------------------------------------------------- casos de uso (cliente)


def crear(
    db: Session,
    id_cliente: uuid.UUID,
    data: PedidoCreate,
    cobro_unico: LiquidacionIn | None = None,
) -> PedidoOut:
    """Crea el pedido y reserva el stock. Con `cobro_unico` es una venta directa: sin anticipo,
    con un solo pago confirmado por el total, y el pedido nace ENTREGADO."""
    if db.get(Cliente, id_cliente) is None:
        raise NoAutenticado("Cliente no encontrado")
    dist = db.get(Distribuidor, data.id_distribuidor)
    if dist is None:
        raise NoEncontrado("Distribuidor no encontrado")

    cantidades = {i.id_producto: i.cantidad for i in data.items}
    ids = sorted(cantidades)  # orden fijo: evita bloqueos cruzados entre pedidos simultáneos

    productos = {
        p.id_producto: p
        for p in db.scalars(
            select(Producto).where(
                Producto.id_producto.in_(ids),
                Producto.id_distribuidor == dist.id_distribuidor,
                Producto.activo.is_(True),
            )
        )
    }
    if len(productos) != len(ids):
        raise AppError(
            "Uno o más productos no existen, están desactivados o no son de este distribuidor"
        )

    # Reserva de stock: lotes que caducan primero, sin tocar los vencidos. FOR UPDATE evita
    # vender dos veces lo mismo cuando entran pedidos al mismo tiempo.
    ahora = _ahora_utc().replace(tzinfo=None)
    asignaciones: list[tuple[uuid.UUID, uuid.UUID, int]] = []  # (producto, lote, cantidad)
    for pid in ids:
        lotes = db.scalars(
            select(Stock)
            .join(ProductoStock, ProductoStock.stock_id == Stock.id_stock)
            .where(
                ProductoStock.id_producto == pid,
                Stock.stock > 0,
                Stock.caducidad > ahora,
            )
            .order_by(Stock.caducidad, Stock.id_stock)
            .with_for_update(of=Stock)
        ).all()
        disponible = sum(lote.stock for lote in lotes)
        if disponible < cantidades[pid]:
            db.rollback()  # suelta los bloqueos
            raise Conflicto(
                f"Stock insuficiente de «{productos[pid].nombre}»: "
                f"disponible {disponible}, pedido {cantidades[pid]}"
            )
        resto = cantidades[pid]
        for lote in lotes:
            if resto == 0:
                break
            tomar = min(lote.stock, resto)
            lote.stock -= tomar
            resto -= tomar
            asignaciones.append((pid, lote.id_stock, tomar))

    total = _dinero(sum(cantidades[pid] * productos[pid].precio_unitario for pid in ids))
    anticipo = _dinero(total * float(dist.porcentaje_anticipo) / 100)
    saldo = _dinero(total - anticipo)
    if (total if cobro_unico is not None else anticipo) <= 0:
        db.rollback()
        raise AppError("El monto del pedido es demasiado pequeño")

    # En un cobro único la entrega es inmediata: la base exige las dos fechas para ENTREGADO
    extra = {}
    if cobro_unico is not None:
        extra = {
            "estatus": "ENTREGADO",
            "fecha_entrega_estimada": func.now(),
            "fecha_entrega_real": func.now(),
        }
    pedido = Pedido(
        cliente_id=id_cliente,
        distribuidor_id=dist.id_distribuidor,
        direccion_entrega=data.direccion_entrega,
        **extra,
    )
    db.add(pedido)
    try:
        db.flush()  # genera id_pedido
        db.add_all(
            DetallePedido(
                pedido_id=pedido.id_pedido,
                producto_id=pid,
                cantidad=cantidades[pid],
                precio_unitario=productos[pid].precio_unitario,  # precio congelado
            )
            for pid in ids
        )
        db.flush()
        db.add_all(
            DetallePedidoLote(
                pedido_id=pedido.id_pedido, producto_id=pid, stock_id=sid, cantidad=cant
            )
            for pid, sid, cant in asignaciones
        )
        if cobro_unico is not None:
            ahora_pago = _ahora_utc()
            db.add(
                Pago(
                    pedido_id=pedido.id_pedido,
                    tipo="FINAL",  # el único pago del pedido; no hay anticipo
                    monto=total,
                    estado="CONFIRMADO",
                    metodo=cobro_unico.metodo,
                    referencia=_referencia(pedido.id_pedido, "FINAL"),
                    comprobante_url=cobro_unico.comprobante_url,
                    fecha_comprobante=ahora_pago if cobro_unico.comprobante_url else None,
                    fecha_validacion=ahora_pago,
                )
            )
        else:
            db.add(
                Pago(
                    pedido_id=pedido.id_pedido,
                    tipo="ANTICIPO",
                    monto=anticipo,
                    metodo="TRANSFERENCIA",  # el anticipo siempre es transferencia
                    referencia=_referencia(pedido.id_pedido, "ANTICIPO"),
                )
            )
            if saldo > 0:  # con anticipo del 100% no hay pago final
                db.add(
                    Pago(
                        pedido_id=pedido.id_pedido,
                        tipo="FINAL",
                        monto=saldo,
                        metodo="TRANSFERENCIA",  # se cambia a EFECTIVO al registrar el cobro
                        referencia=_referencia(pedido.id_pedido, "FINAL"),
                    )
                )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflicto("No se pudo crear el pedido, intenta de nuevo")
    db.refresh(pedido)
    return _armar(db, [pedido])[0]


def listar_cliente(
    db: Session, id_cliente: uuid.UUID, tab: TabPedidos, page: int, page_size: int
) -> MisPedidosPage:
    suyo = Pedido.cliente_id == id_cliente

    por_estatus = dict(
        db.execute(select(Pedido.estatus, func.count()).where(suyo).group_by(Pedido.estatus)).all()
    )

    def n(*estatus: str) -> int:
        return sum(por_estatus.get(e, 0) for e in estatus)

    conteos = ConteosPedidos(
        activos=n(*TABS["activos"]),
        entregados=n(*TABS["entregados"]),
        cancelados=n(*TABS["cancelados"]),
    )
    saldo = db.scalar(
        select(func.coalesce(func.sum(Pago.monto), 0))
        .select_from(Pago)
        .join(Pedido, Pedido.id_pedido == Pago.pedido_id)
        .where(
            suyo,
            Pedido.estatus == "EN_ENVIO",
            Pago.tipo == "FINAL",
            Pago.estado.not_in(("CONFIRMADO", "ANULADO")),
        )
    )
    resumen = ResumenMisPedidos(
        en_ruta=n("EN_ENVIO"), en_armado=n("EN_PROCESO"), saldo_por_liquidar=_dinero(saldo or 0)
    )

    pedidos = db.scalars(
        select(Pedido)
        .where(suyo, Pedido.estatus.in_(TABS[tab]))
        .order_by(Pedido.fecha_realizacion.desc(), Pedido.id_pedido)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    total = getattr(conteos, tab)
    return MisPedidosPage(
        pedidos=_armar(db, list(pedidos)),
        conteos=conteos,
        resumen=resumen,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=(total + page_size - 1) // page_size if total else 0,
    )


def obtener(db: Session, user: dict, id_pedido: uuid.UUID) -> PedidoOut:
    """Detalle para el cliente dueño o el distribuidor dueño; para cualquier otro, 404."""
    try:
        uid = uuid.UUID(user["sub"])
    except (KeyError, ValueError):
        raise NoAutenticado("Token inválido")
    stmt = select(Pedido).where(Pedido.id_pedido == id_pedido)
    if user.get("rol") == "cliente":
        stmt = stmt.where(Pedido.cliente_id == uid)
    elif user.get("rol") == "distribuidor":
        stmt = stmt.where(Pedido.distribuidor_id == uid)
    else:
        raise NoAutenticado("Token inválido")
    pedido = db.scalar(stmt)
    if pedido is None:
        raise NoEncontrado("Pedido no encontrado")
    return _armar(db, [pedido])[0]


def cancelar_cliente(
    db: Session, id_cliente: uuid.UUID, id_pedido: uuid.UUID, motivo: str | None
) -> PedidoOut:
    pedido = db.scalar(
        select(Pedido)
        .where(Pedido.id_pedido == id_pedido, Pedido.cliente_id == id_cliente)
        .with_for_update()
    )
    if pedido is None:
        raise NoEncontrado("Pedido no encontrado")

    if pedido.estatus not in CANCELABLES_CLIENTE:
        razon = {
            "EN_ENVIO": "El pedido ya va en ruta y no admite cancelación",
            "ENTREGADO": "El pedido ya fue entregado",
            "CANCELADO": "El pedido ya está cancelado",
        }.get(pedido.estatus, "El pedido no se puede cancelar en este estado")
        db.rollback()
        raise Conflicto(razon)

    return _cancelar(db, pedido, "CLIENTE", motivo)


def _cancelar(db: Session, pedido: Pedido, por: str, motivo: str | None) -> PedidoOut:
    """Cancela un pedido ya bloqueado y validado: devuelve el stock a sus lotes, anula lo no
    cobrado y lo marca cancelado. `por` es CLIENTE o PROVEEDOR."""
    id_pedido = pedido.id_pedido

    # Devuelve a cada lote lo que se le había quitado (orden fijo contra bloqueos cruzados)
    asignaciones = db.scalars(
        select(DetallePedidoLote)
        .where(DetallePedidoLote.pedido_id == id_pedido)
        .order_by(DetallePedidoLote.stock_id)
    ).all()
    for a in asignaciones:
        db.execute(
            update(Stock).where(Stock.id_stock == a.stock_id).values(stock=Stock.stock + a.cantidad)
        )

    # Pagos: lo no cobrado se anula. Un anticipo ya CONFIRMADO se queda así (hay que
    # reembolsarlo; el pedido lo marca con reembolso_pendiente).
    for pago in db.scalars(select(Pago).where(Pago.pedido_id == id_pedido)):
        if pago.estado in ("PENDIENTE", "POR_VALIDAR"):
            pago.estado = "ANULADO"
        elif pago.tipo == "FINAL" and pago.estado != "CONFIRMADO":
            pago.estado = "ANULADO"

    pedido.estatus = "CANCELADO"
    pedido.cancelado_por = por
    pedido.motivo_cancelacion = motivo
    pedido.fecha_cancelacion = _ahora_utc()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflicto("No se pudo cancelar el pedido")
    db.refresh(pedido)
    return _armar(db, [pedido])[0]
