import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import String, cast, delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import Conflicto, NoEncontrado
from app.models import DetallePedidoLote, Producto, ProductoStock, Stock
from app.schemas.lote import (
    ConteosLotes,
    EstadoLote,
    LoteCreate,
    LoteOut,
    LoteUpdate,
    ProductoDeLote,
    Vigencia,
)


# ---------------------------------------------------------------- helpers internos


def _ahora() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC, como la columna


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc)


def _vigencia(caducidad: datetime, ahora: datetime) -> Vigencia:
    restante = caducidad - ahora
    if restante <= timedelta(0):
        return Vigencia.VENCIDO
    if restante <= timedelta(hours=12):
        return Vigencia.ULTIMAS_HORAS
    if restante <= timedelta(hours=48):
        return Vigencia.CONSUMO_RAPIDO
    if restante <= timedelta(days=7):
        return Vigencia.FRESCURA_OPTIMA
    return Vigencia.LARGA_VIDA


def codigo_lote(id_stock: uuid.UUID) -> str:
    """Código corto para mostrar (LT-1A2B3C4D). Se deriva del id; no se guarda."""
    return f"LT-{id_stock.hex[:8].upper()}"


def _a_out(stock: Stock, producto: Producto, fecha_registro: datetime) -> LoteOut:
    ahora = _ahora()
    return LoteOut(
        id_stock=stock.id_stock,
        codigo_lote=codigo_lote(stock.id_stock),
        producto=ProductoDeLote.model_validate(producto),
        stock=stock.stock,
        caducidad=_utc(stock.caducidad),
        fecha_registro=_utc(fecha_registro),
        vigencia=_vigencia(stock.caducidad, ahora),
        por_agotarse=0 < stock.stock <= settings.lote_bajo_stock,
    )


def _base_select(id_distribuidor: uuid.UUID):
    """Lote = Stock + ProductoStock + Producto, solo de este distribuidor."""
    return (
        select(Stock, Producto, ProductoStock.fecha_registro)
        .join(ProductoStock, ProductoStock.stock_id == Stock.id_stock)
        .join(Producto, Producto.id_producto == ProductoStock.id_producto)
        .where(Producto.id_distribuidor == id_distribuidor)
    )


def _filtro_estado(estado: EstadoLote, ahora: datetime):
    if estado == "critica":
        limite = ahora + timedelta(hours=settings.lote_critico_horas)
        return Stock.caducidad <= limite
    if estado == "por_agotarse":
        return (Stock.stock > 0) & (Stock.stock <= settings.lote_bajo_stock)
    return None


def _obtener_producto_propio(
    db: Session, id_distribuidor: uuid.UUID, id_producto: uuid.UUID
) -> Producto:
    producto = db.scalar(
        select(Producto).where(
            Producto.id_producto == id_producto,
            Producto.id_distribuidor == id_distribuidor,
        )
    )
    if producto is None:
        raise NoEncontrado("Producto no encontrado")
    return producto


def _obtener_lote_propio(
    db: Session, id_distribuidor: uuid.UUID, id_stock: uuid.UUID
) -> tuple[Stock, Producto, datetime]:
    fila = db.execute(_base_select(id_distribuidor).where(Stock.id_stock == id_stock)).first()
    if fila is None:
        raise NoEncontrado("Lote no encontrado")  # no revela lotes de otros distribuidores
    return fila[0], fila[1], fila[2]


# ---------------------------------------------------------------- casos de uso


def listar(
    db: Session,
    id_distribuidor: uuid.UUID,
    estado: EstadoLote,
    q: str | None,
    id_producto: uuid.UUID | None,
    page: int,
    page_size: int,
) -> tuple[list[LoteOut], ConteosLotes, int]:
    ahora = _ahora()

    filtros = []
    if id_producto:
        filtros.append(Producto.id_producto == id_producto)
    if q and q.strip():
        t = q.strip()
        filtros.append(
            or_(
                Producto.nombre.icontains(t, autoescape=True),
                Producto.codigo_generado.icontains(t, autoescape=True),
                # "LT-1A2B3C4D" o solo "1a2b": compara contra el inicio del id
                cast(Stock.id_stock, String).istartswith(
                    t.lower().removeprefix("lt-").removeprefix("#lt-"), autoescape=True
                ),
            )
        )

    def contar(extra=None) -> int:
        stmt = (
            select(func.count())
            .select_from(Stock)
            .join(ProductoStock, ProductoStock.stock_id == Stock.id_stock)
            .join(Producto, Producto.id_producto == ProductoStock.id_producto)
            .where(Producto.id_distribuidor == id_distribuidor, *filtros)
        )
        if extra is not None:
            stmt = stmt.where(extra)
        return db.scalar(stmt) or 0

    conteos = ConteosLotes(
        todos=contar(),
        critica=contar(_filtro_estado("critica", ahora)),
        por_agotarse=contar(_filtro_estado("por_agotarse", ahora)),
    )
    total = getattr(conteos, estado)

    stmt = _base_select(id_distribuidor).where(*filtros)
    extra = _filtro_estado(estado, ahora)
    if extra is not None:
        stmt = stmt.where(extra)
    filas = db.execute(
        stmt.order_by(Stock.caducidad, Stock.id_stock)  # los que caducan primero arriba
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return [_a_out(s, p, f) for s, p, f in filas], conteos, total


def crear(db: Session, id_distribuidor: uuid.UUID, data: LoteCreate) -> LoteOut:
    producto = _obtener_producto_propio(db, id_distribuidor, data.id_producto)

    stock = Stock(stock=data.stock, caducidad=data.caducidad)
    db.add(stock)
    db.flush()  # genera id_stock
    link = ProductoStock(id_producto=producto.id_producto, stock_id=stock.id_stock)
    db.add(link)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflicto("No se pudo registrar el lote")
    db.refresh(stock)
    db.refresh(link)
    return _a_out(stock, producto, link.fecha_registro)


def obtener(db: Session, id_distribuidor: uuid.UUID, id_stock: uuid.UUID) -> LoteOut:
    s, p, f = _obtener_lote_propio(db, id_distribuidor, id_stock)
    return _a_out(s, p, f)


def editar(
    db: Session, id_distribuidor: uuid.UUID, id_stock: uuid.UUID, data: LoteUpdate
) -> LoteOut:
    s, p, f = _obtener_lote_propio(db, id_distribuidor, id_stock)
    for campo, valor in data.model_dump(exclude_unset=True).items():
        setattr(s, campo, valor)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflicto("No se pudo actualizar el lote")
    db.refresh(s)
    return _a_out(s, p, f)


def borrar(db: Session, id_distribuidor: uuid.UUID, id_stock: uuid.UUID) -> None:
    """Borrado real, solo si el lote nunca se asignó a un pedido."""
    s, _p, _f = _obtener_lote_propio(db, id_distribuidor, id_stock)

    usado = db.scalar(
        select(DetallePedidoLote.pedido_id).where(DetallePedidoLote.stock_id == id_stock).limit(1)
    )
    if usado is not None:
        raise Conflicto(
            "Este lote ya se asignó a pedidos y no se puede borrar. "
            "Déjalo en 0 con PATCH /lotes/{id} y {\"stock\": 0}"
        )
    try:
        db.execute(delete(ProductoStock).where(ProductoStock.stock_id == id_stock))
        db.delete(s)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflicto("No se pudo borrar el lote porque tiene registros ligados")
