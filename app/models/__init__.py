# Importa todos los modelos aquí para que SQLAlchemy resuelva las relaciones entre ellos.
from app.models.cliente import Cliente
from app.models.distribuidor import Distribuidor
from app.models.pedido import DetallePedido
from app.models.producto import CategoriaPostre, Producto
from app.models.stock import ProductoStock, Stock

__all__ = [
    "Cliente",
    "Distribuidor",
    "DetallePedido",
    "CategoriaPostre",
    "Producto",
    "ProductoStock",
    "Stock",
]
