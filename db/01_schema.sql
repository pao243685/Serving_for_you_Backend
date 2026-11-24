-- =====================================================================
-- Serving for you – 01_schema.sql (v3)
-- Solo tablas, índices y tipos. Sin CREATE DATABASE / \c (compatible con Supabase).
-- Orden de ejecución: 01_schema -> 02_roles -> 03_funciones_triggers -> 04_permisos_rls
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TYPE categoria_postre AS ENUM (
    'Pasteles', 'Gelatinas y Flanes', 'Helados',
    'Galletas', 'Mousse y Cremas', 'Panadería Dulce'
);

CREATE TABLE distribuidores (
    id_distribuidor      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre_marca         VARCHAR(100) NOT NULL CHECK (TRIM(nombre_marca) <> ''),
    nombre_encargado     VARCHAR(200) NOT NULL CHECK (TRIM(nombre_encargado) <> ''),
    correo               TEXT NOT NULL UNIQUE CHECK (correo ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
    contrasena           TEXT NOT NULL,          -- hash Argon2 generado por el backend
    telefono             VARCHAR(10) NOT NULL CHECK (telefono ~ '^[0-9]{10}$'),
    direccion_local      TEXT NOT NULL CHECK (TRIM(direccion_local) <> ''),
    terminos_condiciones BOOLEAN NOT NULL DEFAULT FALSE CHECK (terminos_condiciones),
    banco                VARCHAR(100) CHECK (TRIM(banco) <> ''),
    titular              VARCHAR(200) CHECK (TRIM(titular) <> ''),
    clabe                VARCHAR(18)  CHECK (clabe ~ '^[0-9]{18}$'),
    porcentaje_anticipo  NUMERIC(5,2) NOT NULL DEFAULT 50
                         CHECK (porcentaje_anticipo > 0 AND porcentaje_anticipo <= 100),
    -- los tres datos bancarios van completos o vacíos
    CHECK ((banco IS NULL) = (titular IS NULL) AND (banco IS NULL) = (clabe IS NULL))
);

CREATE TABLE clientes (
    id_cliente UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre     VARCHAR(200) NOT NULL CHECK (TRIM(nombre) <> ''),
    correo     TEXT NOT NULL UNIQUE CHECK (correo ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
    contrasena TEXT NOT NULL,
    telefono   VARCHAR(10) NOT NULL CHECK (telefono ~ '^[0-9]{10}$')
);

CREATE TABLE productos (
    id_producto          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    id_distribuidor      UUID NOT NULL REFERENCES distribuidores(id_distribuidor),
    imagen_url           TEXT NOT NULL,
    nombre               VARCHAR(255) NOT NULL CHECK (TRIM(nombre) <> ''),
    unidad_medida        VARCHAR(20) NOT NULL CHECK (unidad_medida IN ('KG', 'L', 'PZ')),
    tamano               VARCHAR(20) CHECK (tamano IN ('PEQUEÑO', 'MEDIANO', 'GRANDE')),
    precio_unitario      NUMERIC(10,2) NOT NULL CHECK (precio_unitario > 0),
    codigo_generado      VARCHAR(12) NOT NULL,   -- lo da el backend; si viene NULL, un trigger lo genera
    categoria            categoria_postre NOT NULL,
    descripcion_producto TEXT,
    activo               BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (id_distribuidor, codigo_generado)
);
-- Mismo nombre + unidad + tamaño no se repite dentro del catálogo de un distribuidor
CREATE UNIQUE INDEX ux_productos_no_duplicados
    ON productos (id_distribuidor, LOWER(TRIM(nombre)), unidad_medida, COALESCE(tamano, ''));

-- Cada fila de 'stock' es un LOTE; 'stock' = unidades que quedan en ese lote
CREATE TABLE stock (
    id_stock  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    stock     INT NOT NULL CHECK (stock >= 0),
    caducidad TIMESTAMPTZ NOT NULL
);

CREATE TABLE productos_stock (
    id_producto_stock UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    id_producto       UUID NOT NULL REFERENCES productos(id_producto),
    stock_id          UUID NOT NULL UNIQUE REFERENCES stock(id_stock),   -- 1 lote = 1 producto
    fecha_registro    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP     -- la fija un trigger
);

CREATE TABLE pedidos (
    id_pedido              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cliente_id             UUID NOT NULL REFERENCES clientes(id_cliente),
    distribuidor_id        UUID NOT NULL REFERENCES distribuidores(id_distribuidor),
    estatus                VARCHAR(20) NOT NULL DEFAULT 'PENDIENTE'
                           CHECK (estatus IN ('PENDIENTE','POR_VALIDAR','EN_PROCESO',
                                              'EN_ENVIO','ENTREGADO','CANCELADO')),
    direccion_entrega      TEXT NOT NULL CHECK (TRIM(direccion_entrega) <> ''),
    total                  NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (total >= 0),
    fecha_realizacion      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fecha_entrega_estimada TIMESTAMPTZ,       -- la fija el proveedor al validar el anticipo
    fecha_entrega_real     TIMESTAMPTZ,       -- la fija el sistema al pasar a ENTREGADO
    cancelado_por          VARCHAR(10) CHECK (cancelado_por IN ('CLIENTE','PROVEEDOR','SISTEMA')),
    motivo_cancelacion     TEXT,
    fecha_cancelacion      TIMESTAMPTZ,
    clave_idempotencia     UUID,              -- evita pedidos duplicados por doble clic / reintento
    UNIQUE (cliente_id, clave_idempotencia),
    CHECK (fecha_entrega_estimada IS NULL OR fecha_entrega_estimada >= fecha_realizacion),
    CHECK (fecha_entrega_real     IS NULL OR fecha_entrega_real     >= fecha_realizacion),
    CHECK ((estatus = 'CANCELADO') = (cancelado_por IS NOT NULL)),
    CHECK ((estatus = 'ENTREGADO') = (fecha_entrega_real IS NOT NULL)),
    CHECK (estatus NOT IN ('EN_PROCESO','EN_ENVIO','ENTREGADO') OR fecha_entrega_estimada IS NOT NULL),
    CHECK (cancelado_por IS DISTINCT FROM 'PROVEEDOR' OR TRIM(COALESCE(motivo_cancelacion,'')) <> '')
);

CREATE TABLE detalle_pedidos (
    pedido_id       UUID NOT NULL REFERENCES pedidos(id_pedido),
    producto_id     UUID NOT NULL REFERENCES productos(id_producto),
    cantidad        INT NOT NULL CHECK (cantidad > 0),
    precio_unitario NUMERIC(10,2) NOT NULL CHECK (precio_unitario > 0),   -- precio congelado
    subtotal        NUMERIC(12,2) GENERATED ALWAYS AS (cantidad * precio_unitario) STORED,
    PRIMARY KEY (pedido_id, producto_id)
);

-- De qué lote(s) salió cada línea del pedido (necesario para devolver el stock al cancelar)
CREATE TABLE detalle_pedido_lotes (
    pedido_id   UUID NOT NULL,
    producto_id UUID NOT NULL,
    stock_id    UUID NOT NULL REFERENCES stock(id_stock),
    cantidad    INT  NOT NULL CHECK (cantidad > 0),
    PRIMARY KEY (pedido_id, producto_id, stock_id),
    FOREIGN KEY (pedido_id, producto_id) REFERENCES detalle_pedidos(pedido_id, producto_id)
);

CREATE TABLE pagos (
    id_pago                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pedido_id                 UUID NOT NULL REFERENCES pedidos(id_pedido),
    tipo                      VARCHAR(10) NOT NULL CHECK (tipo IN ('ANTICIPO','FINAL')),
    monto                     NUMERIC(10,2) NOT NULL CHECK (monto > 0),
    estado                    VARCHAR(20) NOT NULL DEFAULT 'PENDIENTE'
                              CHECK (estado IN ('PENDIENTE','POR_VALIDAR','CONFIRMADO','RECHAZADO','ANULADO')),
    metodo                    VARCHAR(20) NOT NULL DEFAULT 'TRANSFERENCIA'
                              CHECK (metodo IN ('TRANSFERENCIA','EFECTIVO')),
    referencia                VARCHAR(20) NOT NULL,
    comprobante_url           TEXT,
    motivo_rechazo            TEXT,
    fecha_creacion            TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fecha_comprobante         TIMESTAMPTZ,
    fecha_validacion          TIMESTAMPTZ,
    UNIQUE (pedido_id, tipo),
    CHECK (tipo = 'FINAL' OR metodo = 'TRANSFERENCIA'),   -- el anticipo siempre es transferencia
    CHECK (comprobante_url IS NULL OR comprobante_url ~* '\.(jpe?g|png|pdf)(\?.*)?$'),
    CHECK (NOT (metodo = 'TRANSFERENCIA' AND estado IN ('POR_VALIDAR','CONFIRMADO'))
           OR comprobante_url IS NOT NULL),
    CHECK (estado <> 'RECHAZADO' OR TRIM(COALESCE(motivo_rechazo,'')) <> '')
);

-- Bitácoras (las llenan triggers; nadie las edita)
CREATE TABLE pedido_historial (
    id_historial     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pedido_id        UUID NOT NULL REFERENCES pedidos(id_pedido),
    estatus_anterior VARCHAR(20),
    estatus_nuevo    VARCHAR(20) NOT NULL,
    usuario_id       UUID,                      -- NULL = acción del sistema
    fecha            TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE pago_historial (
    id_historial    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pago_id         UUID NOT NULL REFERENCES pagos(id_pago),
    estado_anterior VARCHAR(20),
    estado_nuevo    VARCHAR(20) NOT NULL,
    comprobante_url TEXT,                       -- conserva cada comprobante, aunque se sustituya
    motivo          TEXT,
    usuario_id      UUID,
    fecha           TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX ix_pedidos_cliente       ON pedidos (cliente_id);
CREATE INDEX ix_pedidos_distribuidor  ON pedidos (distribuidor_id, estatus);
CREATE INDEX ix_productos_dist        ON productos (id_distribuidor);
CREATE INDEX ix_productos_stock_prod  ON productos_stock (id_producto);
CREATE INDEX ix_stock_caducidad       ON stock (caducidad) WHERE stock > 0;
CREATE INDEX ix_pagos_pedido          ON pagos (pedido_id);
CREATE INDEX ix_pedido_historial      ON pedido_historial (pedido_id);
CREATE INDEX ix_pago_historial        ON pago_historial (pago_id);
