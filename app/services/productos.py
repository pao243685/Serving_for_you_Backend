import secrets
import string
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import Conflicto, ErrorInterno, NoAutenticado, NoEncontrado
from app.models import (
    CategoriaPostre,
    DetallePedido,
    Distribuidor,
    Producto,
    ProductoStock,
    Stock,
)
from app.schemas.producto import ConteosCatalogo, ProductoCreate, ProductoUpdate

PREFIJOS = {
    CategoriaPostre.PASTELES: "PAS",
    CategoriaPostre.GELATINAS_FLANES: "GEL",
    CategoriaPostre.HELADOS: "HEL",
    CategoriaPostre.GALLETAS: "GAL",
    CategoriaPostre.MOUSSE_CREMAS: "MOU",
    CategoriaPostre.PANADERIA_DULCE: "PAN",
}
_ALFABETO = string.ascii_uppercase + string.digits
MSG_DUPLICADO = (
    "Ya tienes un producto con ese nombre, unidad y tamaño "
    "(revisa también los desactivados)"
)


# ---------------------------------------------------------------- helpers internos


def _generar_codigo(categoria: CategoriaPostre) -> str:
    sufijo = "".join(secrets.choice(_ALFABETO) for _ in range(6))
    return f"{PREFIJOS[categoria]}-{sufijo}"  # 10 caracteres, la columna admite 12


def _duplicado(
    db: Session,
    id_distribuidor: uuid.UUID,
    nombre: str,
    unidad_medida: str,
    tamano: str | None,
    excluir: uuid.UUID | None = None,
) -> bool:
    """Misma regla que el índice ux_productos_no_duplicados."""
    q = select(Producto.id_producto).where(
        Producto.id_distribuidor == id_distribuidor,
        func.lower(func.trim(Producto.nombre)) == func.lower(func.trim(nombre)),
        Producto.unidad_medida == unidad_medida,
        func.coalesce(Producto.tamano, "") == (tamano or ""),
    )
    if excluir is not None:
        q = q.where(Producto.id_producto != excluir)
    return db.scalar(q.limit(1)) is not None


def obtener_propio(db: Session, id_distribuidor: uuid.UUID, id_producto: uuid.UUID) -> Producto:
    """Devuelve el producto solo si es del distribuidor; si no, 404 (no revela que existe)."""
    producto = db.scalar(
        select(Producto).where(
            Producto.id_producto == id_producto,
            Producto.id_distribuidor == id_distribuidor,
        )
    )
    if producto is None:
        raise NoEncontrado("Producto no encontrado")
    return producto


# ---------------------------------------------------------------- casos de uso


def _poner_stock_disponible(db: Session, productos: list[Producto]) -> None:
    """Agrega `stock_disponible` a cada producto: unidades en lotes sin vencer, la misma regla
    con la que se reserva el stock al crear un pedido."""
    if not productos:
        return
    ahora = datetime.now(timezone.utc).replace(tzinfo=None)
    por_producto = dict(
        db.execute(
            select(ProductoStock.id_producto, func.sum(Stock.stock))
            .join(Stock, Stock.id_stock == ProductoStock.stock_id)
            .where(
                ProductoStock.id_producto.in_([p.id_producto for p in productos]),
                Stock.stock > 0,
                Stock.caducidad > ahora,
            )
            .group_by(ProductoStock.id_producto)
        ).all()
    )
    for p in productos:
        p.stock_disponible = int(por_producto.get(p.id_producto, 0))


def conteos(
    db: Session, id_distribuidor: uuid.UUID, activo: bool | None, q: str | None
) -> ConteosCatalogo:
    """Cuántos productos hay por unidad y por categoría, para los números de las pestañas."""
    filtros = [Producto.id_distribuidor == id_distribuidor]
    if q and q.strip():
        t = q.strip()
        filtros.append(
            or_(
                Producto.nombre.icontains(t, autoescape=True),
                Producto.codigo_generado.icontains(t, autoescape=True),
                Producto.descripcion_producto.icontains(t, autoescape=True),
            )
        )
    if activo is not None:
        filtros.append(Producto.activo.is_(activo))

    def agrupar(columna) -> dict:
        filas = db.execute(select(columna, func.count()).where(*filtros).group_by(columna)).all()
        return {getattr(clave, "value", clave): n for clave, n in filas}

    por_unidad = agrupar(Producto.unidad_medida)
    por_categoria = agrupar(Producto.categoria)
    return ConteosCatalogo(
        todos=sum(por_unidad.values()),
        por_unidad={u: por_unidad.get(u, 0) for u in ("PZ", "KG", "L")},
        por_categoria={c.value: por_categoria.get(c.value, 0) for c in CategoriaPostre},
    )


def listar(
    db: Session,
    id_distribuidor: uuid.UUID,
    categoria: CategoriaPostre | None,
    activo: bool | None,
    page: int,
    page_size: int,
    unidad_medida: str | None = None,
    q: str | None = None,
    tamano: str | None = None,
) -> tuple[list[Producto], int]:
    """activo=True para el catálogo de clientes; None o bool para la vista del dueño."""
    filtros = [Producto.id_distribuidor == id_distribuidor]
    if categoria:
        filtros.append(Producto.categoria == categoria)
    if unidad_medida:
        filtros.append(Producto.unidad_medida == unidad_medida)
    if tamano:
        filtros.append(Producto.tamano == tamano)
    if q and q.strip():
        t = q.strip()
        filtros.append(
            or_(
                Producto.nombre.icontains(t, autoescape=True),
                Producto.codigo_generado.icontains(t, autoescape=True),
                Producto.descripcion_producto.icontains(t, autoescape=True),
            )
        )
    if activo is not None:
        filtros.append(Producto.activo.is_(activo))

    total = db.scalar(select(func.count()).select_from(Producto).where(*filtros)) or 0
    items = db.scalars(
        select(Producto)
        .where(*filtros)
        .order_by(Producto.nombre, Producto.id_producto)  # orden estable para paginar
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    items = list(items)
    _poner_stock_disponible(db, items)
    return items, total


def crear(db: Session, id_distribuidor: uuid.UUID, data: ProductoCreate) -> Producto:
    if db.get(Distribuidor, id_distribuidor) is None:
        raise NoAutenticado("Distribuidor no encontrado")

    if _duplicado(db, id_distribuidor, data.nombre, data.unidad_medida, data.tamano):
        raise Conflicto(MSG_DUPLICADO)

    # Reintenta por si el código aleatorio choca (muy improbable)
    for _ in range(5):
        producto = Producto(
            imagen_url=str(data.imagen_url),
            nombre=data.nombre,
            unidad_medida=data.unidad_medida,
            tamano=data.tamano,
            id_distribuidor=id_distribuidor,
            precio_unitario=data.precio_unitario,
            codigo_generado=_generar_codigo(data.categoria),
            categoria=data.categoria,
            descripcion_producto=data.descripcion_producto,
            activo=True,
        )
        db.add(producto)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            if _duplicado(db, id_distribuidor, data.nombre, data.unidad_medida, data.tamano):
                raise Conflicto(MSG_DUPLICADO)  # carrera entre dos peticiones
            continue
        db.refresh(producto)
        return producto

    raise ErrorInterno("No se pudo generar un código único, intenta de nuevo")


def editar(
    db: Session, id_distribuidor: uuid.UUID, id_producto: uuid.UUID, data: ProductoUpdate
) -> Producto:
    producto = obtener_propio(db, id_distribuidor, id_producto)

    cambios = data.model_dump(exclude_unset=True)
    if "imagen_url" in cambios:
        cambios["imagen_url"] = str(cambios["imagen_url"])

    # Si cambia lo que define la identidad del producto, revisa duplicados con los valores finales
    if any(k in cambios for k in ("nombre", "unidad_medida", "tamano")):
        nombre = cambios.get("nombre", producto.nombre)
        unidad = cambios.get("unidad_medida", producto.unidad_medida)
        tamano = cambios["tamano"] if "tamano" in cambios else producto.tamano
        if _duplicado(db, id_distribuidor, nombre, unidad, tamano, excluir=producto.id_producto):
            raise Conflicto(MSG_DUPLICADO)

    for campo, valor in cambios.items():
        setattr(producto, campo, valor)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflicto(MSG_DUPLICADO)
    db.refresh(producto)
    return producto


def borrar(db: Session, id_distribuidor: uuid.UUID, id_producto: uuid.UUID) -> None:
    """Borrado real, solo si el producto nunca se ha pedido. Si ya tiene pedidos, desactívalo."""
    producto = obtener_propio(db, id_distribuidor, id_producto)

    tiene_pedidos = db.scalar(
        select(DetallePedido.pedido_id).where(DetallePedido.producto_id == id_producto).limit(1)
    )
    if tiene_pedidos is not None:
        raise Conflicto(
            "Este producto ya aparece en pedidos y no se puede borrar. "
            'Desactívalo con PATCH /productos/{id} y {"activo": false}'
        )

    try:
        lotes = db.scalars(
            select(ProductoStock.stock_id).where(ProductoStock.id_producto == id_producto)
        ).all()
        db.execute(delete(ProductoStock).where(ProductoStock.id_producto == id_producto))
        if lotes:
            # Borra los lotes que quedaron huérfanos (no ligados a otro producto)
            ligados_a_otros = select(ProductoStock.stock_id)
            db.execute(
                delete(Stock).where(
                    Stock.id_stock.in_(lotes), Stock.id_stock.not_in(ligados_a_otros)
                )
            )
        db.delete(producto)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflicto("No se pudo borrar el producto porque tiene registros ligados")
