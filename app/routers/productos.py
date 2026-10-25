import secrets
import string
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_distribuidor
from app.limiter import limiter
from app.models import CategoriaPostre, Distribuidor, Producto
from app.schemas import ProductoCreado, ProductoCreate, ProductosPage

router = APIRouter(tags=["productos"])

PREFIJOS = {
    CategoriaPostre.PASTELES: "PAS",
    CategoriaPostre.GELATINAS_FLANES: "GEL",
    CategoriaPostre.HELADOS: "HEL",
    CategoriaPostre.GALLETAS: "GAL",
    CategoriaPostre.MOUSSE_CREMAS: "MOU",
    CategoriaPostre.PANADERIA_DULCE: "PAN",
}
_ALFABETO = string.ascii_uppercase + string.digits


def _generar_codigo(categoria: CategoriaPostre) -> str:
    sufijo = "".join(secrets.choice(_ALFABETO) for _ in range(6))
    return f"{PREFIJOS[categoria]}-{sufijo}"  # 10 caracteres, la columna admite 12


def _producto_duplicado(db: Session, id_distribuidor: uuid.UUID, data: ProductoCreate) -> bool:
    """Misma regla que el índice ux_productos_no_duplicados."""
    return (
        db.scalar(
            select(Producto.id_producto).where(
                Producto.id_distribuidor == id_distribuidor,
                func.lower(func.trim(Producto.nombre)) == func.lower(func.trim(data.nombre)),
                Producto.unidad_medida == data.unidad_medida,
                func.coalesce(Producto.tamano, "") == (data.tamano or ""),
            )
        )
        is not None
    )


@router.post("/productos", response_model=ProductoCreado, status_code=201)
@limiter.limit("30/minute")
def crear_producto(
    request: Request,
    data: ProductoCreate,
    db: Session = Depends(get_db),
    id_distribuidor: uuid.UUID = Depends(require_distribuidor),
):
    if db.get(Distribuidor, id_distribuidor) is None:
        raise HTTPException(401, "Distribuidor no encontrado")

    msg_duplicado = (
        "Ya tienes un producto con ese nombre, unidad y tamaño "
        "(revisa también los desactivados)"
    )
    if _producto_duplicado(db, id_distribuidor, data):
        raise HTTPException(409, msg_duplicado)

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
            if _producto_duplicado(db, id_distribuidor, data):  # carrera entre dos peticiones
                raise HTTPException(409, msg_duplicado)
            continue
        db.refresh(producto)
        return producto

    raise HTTPException(500, "No se pudo generar un código único, intenta de nuevo")


@router.get("/categorias", response_model=list[str])
@limiter.limit("60/minute")
def listar_categorias(request: Request, _user: dict = Depends(get_current_user)):
    return [c.value for c in CategoriaPostre]


@router.get("/distribuidores/{id_distribuidor}/productos", response_model=ProductosPage)
@limiter.limit("60/minute")
def productos_del_distribuidor(
    request: Request,
    id_distribuidor: uuid.UUID,
    categoria: CategoriaPostre | None = Query(default=None, description="Filtra por categoría"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    dist = db.get(Distribuidor, id_distribuidor)
    if not dist:
        raise HTTPException(404, "Distribuidor no encontrado")

    filtros = [Producto.id_distribuidor == id_distribuidor, Producto.activo.is_(True)]
    if categoria:
        filtros.append(Producto.categoria == categoria)

    total = db.scalar(select(func.count()).select_from(Producto).where(*filtros)) or 0
    productos = db.scalars(
        select(Producto)
        .where(*filtros)
        .order_by(Producto.nombre, Producto.id_producto)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    return ProductosPage(
        distribuidor=dist,
        productos=productos,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=ProductosPage.pages(total, page_size),
    )