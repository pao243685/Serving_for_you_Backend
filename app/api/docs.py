"""Documentación de la API: guía para el front, errores, ejemplos y requisitos por endpoint.

Todo se agrega al esquema OpenAPI cuando alguien abre /docs o /openapi.json, así los routers
no se llenan de texto. Dos cosas se calculan solas y no se pueden desactualizar:
  * qué endpoints piden token y de qué rol (se lee de las dependencias de cada ruta);
  * los ejemplos (se validan contra los modelos reales; si uno ya no cuadra se omite y
    se avisa en el log, nunca se muestra un ejemplo falso).
Lo único escrito a mano son los mensajes de error por endpoint (ERRORES) y la guía.
"""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI

try:  # FastAPI recientes: los routers incluidos ya no se aplanan en app.routes
    from fastapi.routing import iter_route_contexts
except ImportError:  # versiones anteriores: app.routes ya trae cada APIRoute
    iter_route_contexts = None

from app.api.deps import get_current_user, require_cliente, require_distribuidor
from app.core.config import settings
from app.schemas.auth import LoginIn, RegistroCliente, RegistroDistribuidor, TokenOut
from app.schemas.lote import LoteCreate
from app.schemas.pago import ComprobanteIn, LiquidacionIn, RechazarIn, ValidarAnticipoIn
from app.schemas.pedido import CancelarIn, PedidoCreate, PedidoOut
from app.schemas.pedido_distribuidor import CancelarProveedorIn, PedidoManualIn
from app.schemas.producto import ProductoCreate

log = logging.getLogger(__name__)

_METODOS = {"get", "post", "put", "patch", "delete"}
_PLURAL = {"cliente": "clientes", "distribuidor": "distribuidores"}

# ---------------------------------------------------------------- guía (descripción general)

_GUIA = """
API del portal mayorista **Serving for You**: distribuidores de repostería y panadería artesanal
que venden a cafeterías.

## Empezar en 3 pasos

1. `POST /auth/login` con correo y contraseña. Devuelve `access_token` y `rol`.
2. Manda el token en cada petición: `Authorization: Bearer <access_token>`.
   Aquí en Swagger: botón **Authorize** (arriba a la derecha) y pega solo el token.
3. El token dura __TTL__ minutos. Al expirar la API responde `401`: hay que iniciar sesión otra vez.

Hay dos roles y cada endpoint indica cuál exige:
**cliente** (la cafetería que compra) y **distribuidor** (quien produce y vende).
El front no necesita preguntar el rol al iniciar sesión: la respuesta de login ya lo trae.

## Convenciones

| Tema | Regla |
|---|---|
| Identificadores | UUID. |
| Fechas | ISO 8601 con zona, siempre en UTC (`2026-05-17T15:00:00Z`). Al **enviar** una fecha, incluye la zona (`Z` o `-06:00`); sin zona se toma como UTC. Convierte a hora local solo al mostrar. |
| Dinero | Pesos mexicanos (MXN) como número con 2 decimales. |
| Paginación | `page` (desde 1) y `page_size`. Las respuestas traen `total` y `total_pages`. |
| Errores de negocio | `{"detail": "mensaje en español listo para mostrar"}` con 400, 401, 403, 404 o 409. |
| Errores de validación | `422` con `detail` como lista: `[{"loc": ["body", "campo"], "msg": "...", "type": "..."}]`. |
| Límite de peticiones | `429` con `{"error": "..."}`. Login y registro permiten __RATE__ por IP; el resto tiene su propio límite por minuto. |
| Imágenes y comprobantes | La API no recibe archivos: se mandan como **enlaces https**. Los comprobantes deben terminar en `.jpg`, `.jpeg`, `.png` o `.pdf`. |
| Cliente tipado | `/openapi.json` sirve para generar tipos, por ejemplo `npx openapi-typescript <url>/openapi.json`. |

## Flujo de un pedido

`estatus` dice en qué etapa va y `paso` es el número del stepper de la pantalla (1 a 4).

| estatus | paso | Qué significa | Cómo avanza |
|---|---|---|---|
| `PENDIENTE` | 1 | Creado, falta el comprobante del anticipo (o fue rechazado). | El cliente envía el comprobante, o cancela. |
| `POR_VALIDAR` | 1 | Comprobante enviado. | El distribuidor lo valida (pasa a `EN_PROCESO`) o lo rechaza (vuelve a `PENDIENTE`). |
| `EN_PROCESO` | 2 | Anticipo confirmado, en preparación. | El distribuidor completa el armado y pasa a `EN_ENVIO`. El cliente o el distribuidor aún pueden cancelar. |
| `EN_ENVIO` | 3 | En ruta. **Ya no se puede cancelar.** | El distribuidor confirma la entrega. |
| `ENTREGADO` | 4 | Entregado. | Fin. El saldo se liquida contra entrega. |
| `CANCELADO` | `null` | Cancelado por el cliente o el proveedor. | Si ya había anticipo confirmado, queda `reembolso_pendiente` hasta registrar la devolución. |

- Al crear el pedido se **reserva el stock** (primero los lotes que caducan antes). Cancelar lo devuelve.
- El **anticipo** es el `porcentaje_anticipo` del distribuidor (50 % por defecto) y siempre es por transferencia.
  El **saldo** se cobra contra entrega, en efectivo o por transferencia.
- `estado_cobro` resume el dinero de un pedido; úsalo para las etiquetas de la pantalla de cobranza.
- `acciones` indica qué botones habilitar según el estado del pedido (por ejemplo `completar_armado` o
  `cancelar_cliente`). La API valida el rol, así que cada acción solo la ejecuta quien corresponde.

## Qué endpoints usa cada pantalla

| Pantalla | Endpoints |
|---|---|
| Iniciar sesión y registro | `POST /auth/login`, `POST /auth/registro/cliente`, `POST /auth/registro/distribuidor` |
| Catálogo para cafeterías | `GET /distribuidores`, `GET /distribuidores/{id}/productos` (filtros `categoria`, `unidad_medida`, `q`), `POST /pedidos` |
| Mis pedidos y rastreo | `GET /mis-pedidos?tab=`, `GET /pedidos/{id}`, `POST /pedidos/{id}/cancelar`, `POST /pedidos/{id}/anticipo/comprobante` |
| Catálogo de repostería (distribuidor) | `GET /mis-productos`, `POST /productos`, `PATCH /productos/{id}`, `DELETE /productos/{id}`, `GET /categorias` |
| Lotes y caducidades (y su modal) | `GET /lotes`, `POST /lotes`, `PATCH /lotes/{id}`, `DELETE /lotes/{id}`, `GET /productos/{id}/lotes` |
| Cobranza y anticipos | `GET /cobranza?tab=&q=`, `POST /pedidos/{id}/anticipo/validar`, `POST /pedidos/{id}/anticipo/rechazar`, `POST /pedidos/{id}/liquidacion`, `POST /pedidos/{id}/reembolso` |
| Pedidos en curso (distribuidor) | `GET /pedidos?tab=&q=`, `POST /pedidos/{id}/completar-armado`, `POST /pedidos/{id}/confirmar-entrega`, `POST /pedidos/{id}/cancelar-proveedor`, `POST /pedidos/manual` (Generar orden manual) |

## Lo que el diseño pide y la base de datos no guarda

- `folio` (`PED-1A2B3C4D`) y `codigo_lote` (`LT-1A2B3C4D`) se **derivan del id**; no se pueden elegir ni editar.
- Los lotes no guardan cantidad inicial: muestra "N disponibles", sin barra de porcentaje.
- No hay pago con tarjeta: el anticipo es transferencia y el saldo, efectivo o transferencia.
- Un negocio es un cliente: no hay varias sucursales. La "sucursal" del diseño es el nombre del cliente.
- El cierre de pedidos a las 18:00 no está implementado.
- "Verificado" por línea, "Sin merma" y el historial de cancelaciones no existen: cada pedido guarda un
  solo registro de cancelación (`cancelado_por`, `motivo_cancelacion`, `fecha_cancelacion`).
- La orden manual se captura con el correo de un cliente que ya esté registrado.
"""

DESCRIPCION = _GUIA.replace("__TTL__", str(settings.jwt_expire_minutes)).replace(
    "__RATE__", settings.rate_limit_auth
)

TAGS = [
    {"name": "auth", "description": "Registro e inicio de sesión. Aquí se obtiene el token."},
    {
        "name": "distribuidores",
        "description": "Lo que ve una cafetería: distribuidores disponibles y el catálogo de cada uno.",
    },
    {
        "name": "productos",
        "description": "Catálogo del distribuidor: alta, edición, desactivación y borrado de productos.",
    },
    {
        "name": "lotes",
        "description": "Lotes de producción y fechas de caducidad (solo distribuidor). "
        "El stock disponible de un producto es la suma de sus lotes sin vencer.",
    },
    {
        "name": "pedidos",
        "description": "Pedidos de las cafeterías: crear, consultar, rastrear y cancelar.",
    },
    {
        "name": "pagos",
        "description": "Anticipo, liquidación y reembolsos, y la pantalla de cobranza del distribuidor.",
    },
    {"name": "health", "description": "Verificación de que el servidor está vivo."},
]

SWAGGER_UI = {
    "persistAuthorization": True,  # el token sobrevive a recargar la página
    "displayRequestDuration": True,
    "docExpansion": "list",
    "filter": True,  # cuadro de búsqueda por etiqueta
    "tryItOutEnabled": True,
}

# ---------------------------------------------------------------- errores por endpoint
# {(método, ruta): {código: (descripción, [mensajes de ejemplo])}}
# El 401 y el 403 de los endpoints con token se agregan solos.

_NO_EXISTE = "No existe, o no te pertenece"
_DUPLICADO = "Ya tienes un producto con ese nombre, unidad y tamaño (revisa también los desactivados)"
_EN_PEDIDOS = (
    "Este producto ya aparece en pedidos y no se puede borrar. "
    'Desactívalo con PATCH /productos/{id} y {"activo": false}'
)
_SIN_ANTICIPO_VALIDABLE = "Este pedido no tiene un anticipo esperando validación"


def _e(descripcion: str, *mensajes: str) -> tuple[str, list[str]]:
    return (descripcion, list(mensajes))


ERRORES: dict[tuple[str, str], dict[int, tuple[str, list[str]]]] = {
    ("POST", "/auth/registro/distribuidor"): {
        409: _e("El correo ya existe", "Ese correo ya está registrado")
    },
    ("POST", "/auth/registro/cliente"): {
        409: _e("El correo ya existe", "Ese correo ya está registrado")
    },
    ("POST", "/auth/login"): {
        401: _e("Credenciales incorrectas", "Correo o contraseña incorrectos")
    },
    ("GET", "/distribuidores/{id_distribuidor}/productos"): {
        404: _e(_NO_EXISTE, "Distribuidor no encontrado")
    },
    ("POST", "/productos"): {409: _e("Ya existe un producto igual", _DUPLICADO)},
    ("PATCH", "/productos/{id_producto}"): {
        404: _e(_NO_EXISTE, "Producto no encontrado"),
        409: _e("Quedaría igual a otro producto", _DUPLICADO),
    },
    ("DELETE", "/productos/{id_producto}"): {
        404: _e(_NO_EXISTE, "Producto no encontrado"),
        409: _e(
            "Tiene pedidos o registros ligados",
            _EN_PEDIDOS,
            "No se pudo borrar el producto porque tiene registros ligados",
        ),
    },
    ("POST", "/lotes"): {
        404: _e("El producto no existe o no es tuyo", "Producto no encontrado"),
        409: _e("No se pudo guardar", "No se pudo registrar el lote"),
    },
    ("GET", "/productos/{id_producto}/lotes"): {
        404: _e("El producto no existe o no es tuyo", "Producto no encontrado")
    },
    ("GET", "/lotes/{id_stock}"): {404: _e(_NO_EXISTE, "Lote no encontrado")},
    ("PATCH", "/lotes/{id_stock}"): {
        404: _e(_NO_EXISTE, "Lote no encontrado"),
        409: _e("No se pudo guardar", "No se pudo actualizar el lote"),
    },
    ("DELETE", "/lotes/{id_stock}"): {
        404: _e(_NO_EXISTE, "Lote no encontrado"),
        409: _e(
            "El lote ya se usó en pedidos",
            'Este lote ya se asignó a pedidos y no se puede borrar. '
            'Déjalo en 0 con PATCH /lotes/{id} y {"stock": 0}',
        ),
    },
    ("POST", "/pedidos"): {
        400: _e(
            "Productos inválidos o monto demasiado pequeño",
            "Uno o más productos no existen, están desactivados o no son de este distribuidor",
            "El monto del pedido es demasiado pequeño",
        ),
        404: _e("El distribuidor no existe", "Distribuidor no encontrado"),
        409: _e(
            "No alcanza el stock (no se descontó nada)",
            "Stock insuficiente de «Croissant Mantequilla»: disponible 30, pedido 31",
        ),
    },
    ("GET", "/pedidos/{id_pedido}"): {404: _e(_NO_EXISTE, "Pedido no encontrado")},
    ("POST", "/pedidos/{id_pedido}/cancelar"): {
        404: _e(_NO_EXISTE, "Pedido no encontrado"),
        409: _e(
            "El pedido ya no se puede cancelar",
            "El pedido ya va en ruta y no admite cancelación",
            "El pedido ya fue entregado",
            "El pedido ya está cancelado",
        ),
    },
    ("POST", "/pedidos/{id_pedido}/anticipo/comprobante"): {
        404: _e(_NO_EXISTE, "Pedido no encontrado"),
        409: _e(
            "El pedido no está esperando comprobante",
            "Ya enviaste un comprobante; espera a que el proveedor lo valide",
            "El pedido está cancelado",
            "El anticipo de este pedido ya fue confirmado",
        ),
    },
    ("POST", "/pedidos/{id_pedido}/anticipo/validar"): {
        404: _e(_NO_EXISTE, "Pedido no encontrado"),
        409: _e("No hay anticipo por validar", _SIN_ANTICIPO_VALIDABLE),
    },
    ("POST", "/pedidos/{id_pedido}/anticipo/rechazar"): {
        404: _e(_NO_EXISTE, "Pedido no encontrado"),
        409: _e("No hay anticipo por validar", _SIN_ANTICIPO_VALIDABLE),
    },
    ("POST", "/pedidos/{id_pedido}/liquidacion"): {
        404: _e(_NO_EXISTE, "Pedido no encontrado"),
        409: _e(
            "El saldo no se puede cobrar todavía, o ya se cobró",
            "El saldo se cobra cuando el pedido va en ruta o ya fue entregado",
            "El anticipo de este pedido no está confirmado",
            "Este pedido ya está liquidado: no hay saldo pendiente",
        ),
    },
    ("POST", "/pedidos/{id_pedido}/reembolso"): {
        404: _e(_NO_EXISTE, "Pedido no encontrado"),
        409: _e(
            "No hay anticipo por reembolsar, o ya se reembolsó",
            "Este pedido no tiene un anticipo por reembolsar",
            "El reembolso de este pedido ya se registró",
        ),
    },
}

ERRORES.update(
    {
        ("POST", "/pedidos/manual"): {
            400: _e(
                "Productos inválidos o monto demasiado pequeño",
                "Uno o más productos no existen, están desactivados o no son de este distribuidor",
                "El monto del pedido es demasiado pequeño",
            ),
            404: _e("No hay un cliente con ese correo", "No hay un cliente registrado con ese correo"),
            409: _e(
                "No alcanza el stock (no se descontó nada)",
                "Stock insuficiente de «Croissant Mantequilla»: disponible 30, pedido 31",
            ),
        },
        ("POST", "/pedidos/{id_pedido}/completar-armado"): {
            404: _e(_NO_EXISTE, "Pedido no encontrado"),
            409: _e(
                "El pedido no está en preparación",
                "El pedido todavía no tiene el anticipo confirmado",
                "El pedido ya va en ruta",
                "El pedido ya fue entregado",
                "El pedido está cancelado",
            ),
        },
        ("POST", "/pedidos/{id_pedido}/confirmar-entrega"): {
            404: _e(_NO_EXISTE, "Pedido no encontrado"),
            409: _e(
                "El pedido no va en ruta",
                "El pedido aún no sale a ruta: completa el armado primero",
                "El pedido todavía no tiene el anticipo confirmado",
                "El pedido ya fue entregado",
                "El pedido está cancelado",
            ),
        },
        ("POST", "/pedidos/{id_pedido}/cancelar-proveedor"): {
            404: _e(_NO_EXISTE, "Pedido no encontrado"),
            409: _e(
                "El pedido ya no se puede cancelar",
                "El pedido ya va en ruta y no admite cancelación",
                "El pedido ya fue entregado",
                "El pedido ya está cancelado",
            ),
        },
    }
)

# ---------------------------------------------------------------- tipos y descripciones de campos

CAMPOS_ENUM: dict[str, dict[str, list[str]]] = {
    "PedidoOut": {
        "estatus": ["PENDIENTE", "POR_VALIDAR", "EN_PROCESO", "EN_ENVIO", "ENTREGADO", "CANCELADO"],
    },
    "PagoOut": {
        "estado": ["PENDIENTE", "POR_VALIDAR", "CONFIRMADO", "RECHAZADO", "ANULADO"],
        "metodo": ["TRANSFERENCIA", "EFECTIVO"],
    },
}

DESCRIPCIONES: dict[str, dict[str, str]] = {
    "PedidoOut": {
        "folio": "Código corto para mostrar. Se deriva del id; no se guarda ni se puede editar.",
        "estatus": "Etapa del pedido. Ver el flujo en la descripción general de la API.",
        "paso": "Número del stepper (1 a 4). null si está cancelado.",
        "lineas": "Productos del pedido, con el precio que tenían al momento de comprar.",
        "pagos": "ANTICIPO primero y FINAL después. No hay FINAL si el anticipo es del 100 %.",
        "anticipo_pagado": "true cuando el distribuidor ya confirmó el anticipo.",
        "saldo_restante": "Lo que falta por cobrar contra entrega. 0 si no hay saldo o está cancelado.",
        "monto_cobrado": "Suma de los pagos ya confirmados.",
        "estado_cobro": "Resumen del dinero del pedido, para las etiquetas de cobranza.",
        "cancelable_por_cliente": "true si el cliente todavía puede cancelar (aún no va en ruta).",
        "acciones": "Qué botones habilitar según el estado. La API valida el rol de quien ejecuta cada acción.",
        "reembolso_pendiente": "true si se canceló con anticipo ya confirmado y falta devolverlo.",
    },
    "PagoOut": {
        "referencia": "Concepto que el cliente debe poner en la transferencia.",
        "motivo_rechazo": "Solo si el comprobante fue rechazado.",
    },
    "LoteOut": {
        "codigo_lote": "Código corto para mostrar. Se deriva del id; no se guarda.",
        "por_agotarse": "true si quedan pocas unidades (umbral configurable en el servidor).",
    },
    "ResumenMisPedidos": {
        "saldo_por_liquidar": "Saldo pendiente de los pedidos que van en ruta.",
    },
}


# ---------------------------------------------------------------- ejemplos


def _ejemplos() -> dict[type, dict]:
    futuro = datetime.now(timezone.utc) + timedelta(days=3)
    fecha = futuro.strftime("%Y-%m-%dT%H:%M:%SZ")
    cliente = "3f2b8c1e-6a4d-4e55-9a31-0c1d2e3f4a5b"
    dist = "9b1d7f20-52c3-4a8e-8d6f-1e2a3b4c5d6e"
    pedido = "7c9e6679-7425-40de-944b-e07fc1f90ae7"
    comprobante = "https://ejemplo.com/comprobantes/transferencia-0516.png"
    return {
        LoginIn: {"correo": "gerencia@cacaoygrano.com", "contrasena": "MiClave2026"},
        TokenOut: {
            "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
            "token_type": "bearer",
            "rol": "cliente",
        },
        RegistroCliente: {
            "nombre": "Cafetería Cacao & Grano",
            "correo": "gerencia@cacaoygrano.com",
            "contrasena": "MiClave2026",
            "telefono": "9611234567",
        },
        RegistroDistribuidor: {
            "nombre_marca": "La Madrileña",
            "nombre_encargado": "Laura Montes",
            "correo": "ventas@lamadrilena.com",
            "contrasena": "MiClave2026",
            "telefono": "9617654321",
            "direccion_local": "Av. Central 123, Centro, Tuxtla Gutiérrez",
            "terminos_condiciones": True,
            "banco": "BBVA",
            "titular": "Laura Montes Pérez",
            "clabe": "012345678901234567",
            "porcentaje_anticipo": 50,
        },
        ProductoCreate: {
            "nombre": "Croissant Mantequilla Especial",
            "unidad_medida": "PZ",
            "tamano": "GRANDE",
            "precio_unitario": 28.0,
            "categoria": "Pasteles",
            "descripcion_producto": "Hojaldrado tradicional con 36 capas.",
            "imagen_url": "https://ejemplo.com/img/croissant.jpg",
        },
        LoteCreate: {
            "id_producto": "5d0a8b7e-1c2f-4b3a-9e4d-6f7a8b9c0d1e",
            "stock": 180,
            "caducidad": fecha,
        },
        PedidoCreate: {
            "id_distribuidor": dist,
            "direccion_entrega": "Av. Álvaro Obregón 160, Col. Roma Norte, CDMX",
            "items": [
                {"id_producto": "5d0a8b7e-1c2f-4b3a-9e4d-6f7a8b9c0d1e", "cantidad": 25},
                {"id_producto": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d", "cantidad": 15},
            ],
        },
        CancelarIn: {"motivo": "Me equivoqué de sucursal"},
        CancelarProveedorIn: {"motivo": "Se terminó la masa del lote de hoy"},
        PedidoManualIn: {
            "correo_cliente": "gerencia@cacaoygrano.com",
            "direccion_entrega": "Av. Álvaro Obregón 160, Col. Roma Norte, CDMX",
            "items": [{"id_producto": "5d0a8b7e-1c2f-4b3a-9e4d-6f7a8b9c0d1e", "cantidad": 12}],
        },
        ComprobanteIn: {"comprobante_url": comprobante},
        ValidarAnticipoIn: {"fecha_entrega_estimada": fecha},
        RechazarIn: {"motivo": "El monto transferido no coincide con el anticipo"},
        LiquidacionIn: {"metodo": "TRANSFERENCIA", "comprobante_url": comprobante},
        PedidoOut: {
            "id_pedido": pedido,
            "folio": "PED-7C9E6679",
            "estatus": "EN_PROCESO",
            "paso": 2,
            "cliente": {
                "id_cliente": cliente,
                "nombre": "Cafetería Cacao & Grano",
                "telefono": "9611234567",
            },
            "distribuidor": {
                "id_distribuidor": dist,
                "nombre_marca": "La Madrileña",
                "telefono": "9617654321",
                "banco": "BBVA",
                "titular": "Laura Montes Pérez",
                "clabe": "012345678901234567",
            },
            "direccion_entrega": "Av. Álvaro Obregón 160, Col. Roma Norte, CDMX",
            "fecha_realizacion": "2026-05-15T22:30:00Z",
            "fecha_entrega_estimada": "2026-05-17T15:00:00Z",
            "fecha_entrega_real": None,
            "fecha_cancelacion": None,
            "cancelado_por": None,
            "motivo_cancelacion": None,
            "lineas": [
                {
                    "id_producto": "5d0a8b7e-1c2f-4b3a-9e4d-6f7a8b9c0d1e",
                    "nombre": "Croissant Mantequilla Especial",
                    "tamano": "GRANDE",
                    "unidad_medida": "PZ",
                    "imagen_url": "https://ejemplo.com/img/croissant.jpg",
                    "cantidad": 30,
                    "precio_unitario": 35.0,
                    "subtotal": 1050.0,
                },
                {
                    "id_producto": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
                    "nombre": "Tartaleta de Frutos Rojos",
                    "tamano": "MEDIANO",
                    "unidad_medida": "PZ",
                    "imagen_url": "https://ejemplo.com/img/tartaleta.jpg",
                    "cantidad": 15,
                    "precio_unitario": 52.0,
                    "subtotal": 780.0,
                },
                {
                    "id_producto": "c0ffee00-1234-4abc-9def-0123456789ab",
                    "nombre": "Base Tres Leches",
                    "tamano": None,
                    "unidad_medida": "L",
                    "imagen_url": "https://ejemplo.com/img/tres-leches.jpg",
                    "cantidad": 10,
                    "precio_unitario": 53.5,
                    "subtotal": 535.0,
                },
            ],
            "total_unidades": 55,
            "total_productos": 2365.0,
            "pagos": [
                {
                    "id_pago": "11111111-2222-4333-8444-555555555555",
                    "tipo": "ANTICIPO",
                    "monto": 1182.5,
                    "estado": "CONFIRMADO",
                    "metodo": "TRANSFERENCIA",
                    "referencia": "SFY-7C9E6679-A",
                    "comprobante_url": comprobante,
                    "motivo_rechazo": None,
                    "fecha_creacion": "2026-05-15T22:30:00Z",
                    "fecha_comprobante": "2026-05-15T22:45:00Z",
                    "fecha_validacion": "2026-05-16T01:10:00Z",
                    "fecha_reembolso": None,
                    "comprobante_reembolso_url": None,
                },
                {
                    "id_pago": "66666666-7777-4888-9999-000000000000",
                    "tipo": "FINAL",
                    "monto": 1182.5,
                    "estado": "PENDIENTE",
                    "metodo": "TRANSFERENCIA",
                    "referencia": "SFY-7C9E6679-F",
                    "comprobante_url": None,
                    "motivo_rechazo": None,
                    "fecha_creacion": "2026-05-15T22:30:00Z",
                    "fecha_comprobante": None,
                    "fecha_validacion": None,
                    "fecha_reembolso": None,
                    "comprobante_reembolso_url": None,
                },
            ],
            "anticipo_pagado": True,
            "saldo_restante": 1182.5,
            "cancelable_por_cliente": True,
            "reembolso_pendiente": False,
            "monto_cobrado": 1182.5,
            "estado_cobro": "PENDIENTE_LIQUIDAR",
            "acciones": {
                "subir_comprobante": False,
                "cancelar_cliente": True,
                "validar_anticipo": False,
                "rechazar_anticipo": False,
                "completar_armado": True,
                "confirmar_entrega": False,
                "cancelar_proveedor": True,
                "registrar_liquidacion": False,
                "registrar_reembolso": False,
            },
        },
    }


# ---------------------------------------------------------------- armado del esquema


def _recorrer(dep, acumulado: set) -> None:
    acumulado.add(dep.call)
    for sub in dep.dependencies:
        _recorrer(sub, acumulado)


def _rutas_api(app: FastAPI):
    """Genera (ruta completa, métodos, dependant) de cada endpoint, con o sin routers anidados."""
    rutas = iter_route_contexts(app.routes) if iter_route_contexts else app.routes
    for ruta in rutas:
        dependant = getattr(ruta, "dependant", None)
        path = getattr(ruta, "path", None)
        metodos = getattr(ruta, "methods", None)
        if dependant is not None and path and metodos:
            yield path, metodos, dependant


def _requisitos(app: FastAPI) -> dict[tuple[str, str], dict]:
    """Para cada endpoint: ¿qué rol exige? Se lee de las dependencias reales de la ruta."""
    resultado = {}
    for path, metodos, dependant in _rutas_api(app):
        llamadas: set = set()
        _recorrer(dependant, llamadas)
        rol = (
            "cliente"
            if require_cliente in llamadas
            else "distribuidor"
            if require_distribuidor in llamadas
            else None
        )
        info = {"token": get_current_user in llamadas, "rol": rol}
        for metodo in metodos:
            resultado[(metodo, path)] = info
    return resultado


def _respuesta(descripcion: str, mensajes: list[str], modelo: str = "ErrorOut", campo: str = "detail"):
    return {
        "description": descripcion,
        "content": {
            "application/json": {
                "schema": {"$ref": f"#/components/schemas/{modelo}"},
                "examples": {
                    f"ejemplo_{i}": {"summary": m[:70], "value": {campo: m}}
                    for i, m in enumerate(mensajes, start=1)
                },
            }
        },
    }


def _nota(info: dict) -> str:
    if info.get("rol"):
        return f"**Requiere:** token de **{info['rol']}**."
    if info.get("token"):
        if info.get("detectado"):  # se leyeron las dependencias y no exige un rol en particular
            return "**Requiere:** token (cliente o distribuidor)."
        return "**Requiere:** token."
    return "**Público:** no requiere token."


def _enriquecer(app: FastAPI, schema: dict) -> None:
    comps = schema.setdefault("components", {}).setdefault("schemas", {})
    comps["ErrorOut"] = {
        "title": "ErrorOut",
        "type": "object",
        "required": ["detail"],
        "properties": {"detail": {"type": "string", "title": "Detail"}},
        "description": "Error de negocio. `detail` es un mensaje en español listo para mostrar.",
    }
    comps["LimiteOut"] = {
        "title": "LimiteOut",
        "type": "object",
        "required": ["error"],
        "properties": {"error": {"type": "string", "title": "Error"}},
        "description": "Se superó el límite de peticiones. Espera un momento y reintenta.",
    }

    requisitos = _requisitos(app)
    if not requisitos:
        log.warning("No se pudieron leer las rutas de la app: /docs no mostrará el rol de cada endpoint")
    for ruta, operaciones in schema.get("paths", {}).items():
        for metodo, op in operaciones.items():
            if metodo not in _METODOS:
                continue
            clave = (metodo.upper(), ruta)
            detectado = requisitos.get(clave, {})
            # el token se sabe por el esquema (siempre fiable); el rol, por las dependencias
            info = {
                "token": bool(op.get("security")) or detectado.get("token", False),
                "rol": detectado.get("rol"),
                "detectado": bool(detectado),
            }
            op["description"] = _nota(info) + "\n\n" + op.get("description", "")
            resp = op.setdefault("responses", {})
            if info.get("token"):
                resp["401"] = _respuesta(
                    "Falta el token, es inválido o ya expiró",
                    ["Falta el token de acceso", "Token inválido o expirado"],
                )
            if info.get("rol"):
                resp["403"] = _respuesta(
                    f"Tu token no es de {info['rol']}",
                    [f"Solo los {_PLURAL[info['rol']]} pueden hacer esto"],
                )
            for codigo, (descripcion, mensajes) in ERRORES.get(clave, {}).items():
                resp[str(codigo)] = _respuesta(descripcion, mensajes)
            if ruta != "/health":
                resp["429"] = _respuesta(
                    "Demasiadas peticiones (límite por IP)",
                    ["Rate limit exceeded: 5 per 1 minute"],
                    modelo="LimiteOut",
                    campo="error",
                )

    # Ejemplos: solo se muestran si siguen siendo válidos contra el modelo real
    for modelo, ejemplo in _ejemplos().items():
        try:
            modelo.model_validate(ejemplo)
        except Exception as exc:
            log.warning("Ejemplo de %s desactualizado, se omite en /docs: %s", modelo.__name__, exc)
            continue
        for nombre, esquema in comps.items():
            if nombre == modelo.__name__ or nombre.startswith(modelo.__name__ + "-"):
                esquema["examples"] = [ejemplo]

    for modelo, campos in CAMPOS_ENUM.items():
        for nombre, esquema in comps.items():
            if nombre == modelo or nombre.startswith(modelo + "-"):
                for campo, valores in campos.items():
                    if campo in esquema.get("properties", {}):
                        esquema["properties"][campo]["enum"] = valores

    for modelo, campos in DESCRIPCIONES.items():
        for nombre, esquema in comps.items():
            if nombre == modelo or nombre.startswith(modelo + "-"):
                for campo, texto in campos.items():
                    if campo in esquema.get("properties", {}):
                        esquema["properties"][campo]["description"] = texto


def instalar_openapi(app: FastAPI) -> None:
    """Enriquece el esquema la primera vez que se pide (cuando ya están todas las rutas)."""
    original = app.openapi

    def openapi():
        if getattr(app.state, "openapi_enriquecido", False):
            return app.openapi_schema
        schema = original()
        _enriquecer(app, schema)
        app.state.openapi_enriquecido = True
        return schema

    app.openapi = openapi
