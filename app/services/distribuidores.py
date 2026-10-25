import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import NoEncontrado
from app.models import Distribuidor


def obtener(db: Session, id_distribuidor: uuid.UUID) -> Distribuidor:
    dist = db.get(Distribuidor, id_distribuidor)
    if dist is None:
        raise NoEncontrado("Distribuidor no encontrado")
    return dist


def listar(
    db: Session, q: str | None, page: int, page_size: int
) -> tuple[list[Distribuidor], int]:
    filtros = []
    if q and q.strip():
        filtros.append(Distribuidor.nombre_marca.icontains(q.strip(), autoescape=True))

    total = db.scalar(select(func.count()).select_from(Distribuidor).where(*filtros)) or 0
    items = db.scalars(
        select(Distribuidor)
        .where(*filtros)
        .order_by(Distribuidor.nombre_marca, Distribuidor.id_distribuidor)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return list(items), total
