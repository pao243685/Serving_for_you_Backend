import uuid

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Cliente(Base):
    __tablename__ = "clientes"

    id_cliente: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    nombre: Mapped[str] = mapped_column(String(200))
    correo: Mapped[str] = mapped_column(Text, unique=True)
    contrasena: Mapped[str] = mapped_column(Text)
    telefono: Mapped[str] = mapped_column(String(10))
