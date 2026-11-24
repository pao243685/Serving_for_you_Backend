-- =====================================================================
-- Serving for you – 03_funciones_triggers.sql (v3)
-- Triggers (reglas que SIEMPRE deben cumplirse) y funciones de negocio
-- (operaciones atómicas: o se hace todo o no se hace nada).
-- La contraseña la hashea el BACKEND (Argon2); aquí no se toca.
-- =====================================================================

-- Usuario autenticado de la transacción actual (lo fija el backend con set_config)
CREATE OR REPLACE FUNCTION usuario_actual() RETURNS UUID
LANGUAGE sql STABLE AS $$
    SELECT NULLIF(current_setting('app.usuario_id', true), '')::uuid
$$;

-- =====================================================================
-- A. TRIGGERS
-- =====================================================================

-- A1. Correo siempre en minúsculas y sin espacios
CREATE OR REPLACE FUNCTION normalizar_correo() RETURNS TRIGGER
LANGUAGE plpgsql AS $$
BEGIN
    NEW.correo := LOWER(TRIM(NEW.correo));
    RETURN NEW;
END $$;

CREATE TRIGGER trg_distribuidores_correo BEFORE INSERT OR UPDATE OF correo ON distribuidores
    FOR EACH ROW EXECUTE FUNCTION normalizar_correo();
CREATE TRIGGER trg_clientes_correo BEFORE INSERT OR UPDATE OF correo ON clientes
    FOR EACH ROW EXECUTE FUNCTION normalizar_correo();

-- A2. Código de producto: si el backend no lo manda, se genera (PRD-XXXXXXXX)
CREATE OR REPLACE FUNCTION generar_codigo_producto() RETURNS TRIGGER
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.codigo_generado IS NULL OR TRIM(NEW.codigo_generado) = '' THEN
        LOOP
            NEW.codigo_generado := 'PRD-' ||
                UPPER(SUBSTR(MD5(random()::text || clock_timestamp()::text), 1, 8));
            EXIT WHEN NOT EXISTS (SELECT 1 FROM productos
                                  WHERE id_distribuidor = NEW.id_distribuidor
                                    AND codigo_generado = NEW.codigo_generado);
        END LOOP;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_productos_codigo BEFORE INSERT ON productos
    FOR EACH ROW EXECUTE FUNCTION generar_codigo_producto();

-- A3. Lotes: la caducidad debe ser futura (al crear o al cambiarla)
CREATE OR REPLACE FUNCTION validar_caducidad_lote() RETURNS TRIGGER
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND NEW.caducidad = OLD.caducidad THEN
        RETURN NEW;                       -- solo cambió la cantidad: se permite
    END IF;
    IF NEW.caducidad <= CURRENT_TIMESTAMP THEN
        RAISE EXCEPTION 'La fecha de caducidad debe ser posterior a hoy';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_stock_caducidad BEFORE INSERT OR UPDATE OF caducidad ON stock
    FOR EACH ROW EXECUTE FUNCTION validar_caducidad_lote();

-- A4. productos_stock: fecha_registro automática e inmodificable; caducidad > fecha_registro
CREATE OR REPLACE FUNCTION asignar_fecha_registro() RETURNS TRIGGER
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        NEW.fecha_registro := OLD.fecha_registro;
        RETURN NEW;
    END IF;
    NEW.fecha_registro := CURRENT_TIMESTAMP;
    IF (SELECT caducidad FROM stock WHERE id_stock = NEW.stock_id) <= NEW.fecha_registro THEN
        RAISE EXCEPTION 'La caducidad del lote debe ser posterior a su fecha de registro';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_productos_stock_fecha BEFORE INSERT OR UPDATE ON productos_stock
    FOR EACH ROW EXECUTE FUNCTION asignar_fecha_registro();

-- A5. Detalle: el producto debe ser del distribuidor del pedido (un pedido = un distribuidor)
CREATE OR REPLACE FUNCTION validar_distribuidor_unico() RETURNS TRIGGER
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pedidos p JOIN productos pr ON pr.id_distribuidor = p.distribuidor_id
        WHERE p.id_pedido = NEW.pedido_id AND pr.id_producto = NEW.producto_id
    ) THEN
        RAISE EXCEPTION 'El producto no pertenece al distribuidor de este pedido';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_detalle_distribuidor BEFORE INSERT OR UPDATE ON detalle_pedidos
    FOR EACH ROW EXECUTE FUNCTION validar_distribuidor_unico();

-- A6. Pedidos: matriz de transiciones de estatus (sección 3.1 del documento de flujos)
CREATE OR REPLACE FUNCTION validar_transicion_estatus() RETURNS TRIGGER
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
    v_anticipo VARCHAR(20);
    v_ok BOOLEAN;
BEGIN
    IF NEW.cliente_id IS DISTINCT FROM OLD.cliente_id
       OR NEW.distribuidor_id IS DISTINCT FROM OLD.distribuidor_id THEN
        RAISE EXCEPTION 'El cliente y el distribuidor de un pedido no se pueden cambiar';
    END IF;

    IF OLD.estatus IN ('ENTREGADO','CANCELADO') THEN
        RAISE EXCEPTION 'El pedido % está % y ya no admite cambios', OLD.id_pedido, OLD.estatus;
    END IF;

    IF NEW.estatus = OLD.estatus THEN
        RETURN NEW;                       -- cambios en otros campos (p. ej. total)
    END IF;

    v_ok := CASE
        WHEN OLD.estatus = 'PENDIENTE'   AND NEW.estatus IN ('POR_VALIDAR','CANCELADO')            THEN TRUE
        WHEN OLD.estatus = 'POR_VALIDAR' AND NEW.estatus IN ('EN_PROCESO','PENDIENTE','CANCELADO') THEN TRUE
        WHEN OLD.estatus = 'EN_PROCESO'  AND NEW.estatus IN ('EN_ENVIO','CANCELADO')               THEN TRUE
        WHEN OLD.estatus = 'EN_ENVIO'    AND NEW.estatus = 'ENTREGADO'                             THEN TRUE
        ELSE FALSE END;
    IF NOT v_ok THEN
        RAISE EXCEPTION 'Transición no permitida: % -> % (pedido %)',
                        OLD.estatus, NEW.estatus, OLD.id_pedido;
    END IF;

    SELECT estado INTO v_anticipo FROM pagos
    WHERE pedido_id = NEW.id_pedido AND tipo = 'ANTICIPO';

    IF NEW.estatus = 'POR_VALIDAR' AND v_anticipo IS DISTINCT FROM 'POR_VALIDAR' THEN
        RAISE EXCEPTION 'Falta adjuntar el comprobante del anticipo';
    END IF;
    IF NEW.estatus = 'EN_PROCESO' AND v_anticipo IS DISTINCT FROM 'CONFIRMADO' THEN
        RAISE EXCEPTION 'El anticipo debe estar confirmado para pasar a EN_PROCESO';
    END IF;
    IF NEW.estatus = 'PENDIENTE' AND v_anticipo IS DISTINCT FROM 'RECHAZADO' THEN
        RAISE EXCEPTION 'Solo se regresa a PENDIENTE cuando el comprobante fue rechazado';
    END IF;

    IF NEW.estatus = 'CANCELADO' THEN
        IF NEW.cancelado_por = 'PROVEEDOR' AND OLD.estatus = 'PENDIENTE' THEN
            RAISE EXCEPTION 'El proveedor solo puede rechazar pedidos con comprobante o en proceso';
        END IF;
        IF NEW.cancelado_por = 'SISTEMA' AND OLD.estatus <> 'PENDIENTE' THEN
            RAISE EXCEPTION 'La cancelación automática solo aplica a pedidos PENDIENTES';
        END IF;
        NEW.fecha_cancelacion := CURRENT_TIMESTAMP;
    END IF;

    IF NEW.estatus = 'ENTREGADO' THEN
        IF EXISTS (SELECT 1 FROM pagos WHERE pedido_id = NEW.id_pedido AND estado <> 'CONFIRMADO') THEN
            RAISE EXCEPTION 'No se puede entregar: hay pagos sin confirmar';
        END IF;
        NEW.fecha_entrega_real := CURRENT_TIMESTAMP;
    END IF;

    RETURN NEW;
END $$;

CREATE TRIGGER trg_pedidos_validar_estatus BEFORE UPDATE ON pedidos
    FOR EACH ROW EXECUTE FUNCTION validar_transicion_estatus();

-- A7. Cancelación: devuelve el stock a SUS lotes y resuelve los pagos (misma transacción)
--   PENDIENTE / POR_VALIDAR / RECHAZADO -> ANULADO
--   CONFIRMADO                          -> se queda CONFIRMADO. NO HAY REEMBOLSOS: una vez
--                                          efectuado y confirmado el pago, no se devuelve
--                                          (cancele quien cancele).
CREATE OR REPLACE FUNCTION efectos_cancelacion() RETURNS TRIGGER
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
    UPDATE stock s SET stock = s.stock + l.cantidad
    FROM detalle_pedido_lotes l
    WHERE l.pedido_id = NEW.id_pedido AND s.id_stock = l.stock_id;

    UPDATE pagos SET estado = 'ANULADO'
    WHERE pedido_id = NEW.id_pedido
      AND estado IN ('PENDIENTE','POR_VALIDAR','RECHAZADO');
    RETURN NEW;
END $$;

CREATE TRIGGER trg_pedidos_cancelacion AFTER UPDATE OF estatus ON pedidos
    FOR EACH ROW WHEN (OLD.estatus IS DISTINCT FROM NEW.estatus AND NEW.estatus = 'CANCELADO')
    EXECUTE FUNCTION efectos_cancelacion();

-- A8. Pagos: ANULADO y CONFIRMADO son estados finales (sin reembolsos)
CREATE OR REPLACE FUNCTION validar_estado_pago() RETURNS TRIGGER
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.estado IN ('ANULADO','CONFIRMADO') AND NEW.estado <> OLD.estado THEN
        RAISE EXCEPTION 'El pago está % y ya no admite cambios de estado', OLD.estado;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_pagos_estado BEFORE UPDATE ON pagos
    FOR EACH ROW EXECUTE FUNCTION validar_estado_pago();

-- A9. Bitácoras: quién cambió qué y cuándo (se conserva cada comprobante rechazado)
CREATE OR REPLACE FUNCTION registrar_historial_pedido() RETURNS TRIGGER
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO pedido_historial (pedido_id, estatus_anterior, estatus_nuevo, usuario_id)
        VALUES (NEW.id_pedido, NULL, NEW.estatus, usuario_actual());
    ELSIF OLD.estatus IS DISTINCT FROM NEW.estatus THEN
        INSERT INTO pedido_historial (pedido_id, estatus_anterior, estatus_nuevo, usuario_id)
        VALUES (NEW.id_pedido, OLD.estatus, NEW.estatus, usuario_actual());
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_pedidos_historial AFTER INSERT OR UPDATE OF estatus ON pedidos
    FOR EACH ROW EXECUTE FUNCTION registrar_historial_pedido();

CREATE OR REPLACE FUNCTION registrar_historial_pago() RETURNS TRIGGER
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
    IF OLD.estado IS DISTINCT FROM NEW.estado THEN
        INSERT INTO pago_historial (pago_id, estado_anterior, estado_nuevo, comprobante_url, motivo, usuario_id)
        VALUES (NEW.id_pago, OLD.estado, NEW.estado, NEW.comprobante_url, NEW.motivo_rechazo, usuario_actual());
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER trg_pagos_historial AFTER UPDATE OF estado ON pagos
    FOR EACH ROW EXECUTE FUNCTION registrar_historial_pago();

-- =====================================================================
-- B. VISTAS
-- =====================================================================

-- Catálogo para clientes: solo productos activos con existencia vigente (lotes no caducados)
CREATE OR REPLACE VIEW catalogo_disponible AS
SELECT p.id_producto, p.id_distribuidor, p.nombre, p.unidad_medida, p.tamano,
       p.precio_unitario, p.categoria, p.descripcion_producto, p.imagen_url,
       p.codigo_generado, SUM(s.stock)::INT AS existencia
FROM productos p
JOIN productos_stock ps ON ps.id_producto = p.id_producto
JOIN stock s ON s.id_stock = ps.stock_id
WHERE p.activo AND s.stock > 0 AND s.caducidad > CURRENT_TIMESTAMP
GROUP BY p.id_producto
HAVING SUM(s.stock) > 0;

-- Datos públicos del distribuidor (NUNCA correo, contraseña ni datos bancarios)
CREATE OR REPLACE VIEW distribuidores_publico AS
SELECT id_distribuidor, nombre_marca, nombre_encargado, telefono, direccion_local, porcentaje_anticipo
FROM distribuidores;

-- =====================================================================
-- C. FUNCIONES DE NEGOCIO (cada una es una transacción atómica)
--    El usuario sale de usuario_actual(): nadie puede actuar a nombre de otro.
-- =====================================================================

-- C1. Alta de producto + lote inicial + relación (una sola transacción)
CREATE OR REPLACE FUNCTION registrar_producto(
    p_nombre TEXT, p_unidad TEXT, p_tamano TEXT, p_precio NUMERIC, p_imagen_url TEXT,
    p_categoria categoria_postre, p_descripcion TEXT, p_cantidad INT, p_caducidad TIMESTAMPTZ,
    p_codigo TEXT DEFAULT NULL
) RETURNS UUID
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE v_dist UUID := usuario_actual(); v_prod UUID; v_stock UUID;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM distribuidores WHERE id_distribuidor = v_dist) THEN
        RAISE EXCEPTION 'Solo un distribuidor autenticado puede registrar productos';
    END IF;
    IF p_cantidad IS NULL OR p_cantidad < 0 THEN
        RAISE EXCEPTION 'La cantidad inicial debe ser un entero mayor o igual a 0';
    END IF;

    INSERT INTO productos (id_distribuidor, imagen_url, nombre, unidad_medida, tamano,
                           precio_unitario, categoria, descripcion_producto, codigo_generado)
    VALUES (v_dist, p_imagen_url, p_nombre, p_unidad, p_tamano,
            p_precio, p_categoria, p_descripcion, p_codigo)
    RETURNING id_producto INTO v_prod;

    INSERT INTO stock (stock, caducidad) VALUES (p_cantidad, p_caducidad)
    RETURNING id_stock INTO v_stock;
    INSERT INTO productos_stock (id_producto, stock_id) VALUES (v_prod, v_stock);
    RETURN v_prod;
END $$;

-- C2. Reabastecimiento: siempre un lote NUEVO (no se sobrescribe el anterior)
CREATE OR REPLACE FUNCTION reabastecer_stock(p_producto UUID, p_cantidad INT, p_caducidad TIMESTAMPTZ)
RETURNS UUID
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE v_stock UUID;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM productos
                   WHERE id_producto = p_producto AND id_distribuidor = usuario_actual()) THEN
        RAISE EXCEPTION 'El producto no existe o no pertenece al distribuidor';
    END IF;
    IF p_cantidad IS NULL OR p_cantidad <= 0 THEN
        RAISE EXCEPTION 'La cantidad debe ser un entero mayor a 0';
    END IF;
    INSERT INTO stock (stock, caducidad) VALUES (p_cantidad, p_caducidad)
    RETURNING id_stock INTO v_stock;
    INSERT INTO productos_stock (id_producto, stock_id) VALUES (p_producto, v_stock);
    RETURN v_stock;
END $$;

-- C3. Borrar un lote (solo si ningún pedido salió de él)
CREATE OR REPLACE FUNCTION borrar_lote(p_stock UUID) RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM productos_stock ps JOIN productos p ON p.id_producto = ps.id_producto
                   WHERE ps.stock_id = p_stock AND p.id_distribuidor = usuario_actual()) THEN
        RAISE EXCEPTION 'Lote no encontrado';
    END IF;
    IF EXISTS (SELECT 1 FROM detalle_pedido_lotes WHERE stock_id = p_stock) THEN
        RAISE EXCEPTION 'El lote ya se usó en pedidos; ponlo en 0 en lugar de borrarlo';
    END IF;
    DELETE FROM productos_stock WHERE stock_id = p_stock;
    DELETE FROM stock WHERE id_stock = p_stock;
END $$;

-- C4. Borrar un producto (solo si nunca se pidió; si no, desactívalo con activo = false)
CREATE OR REPLACE FUNCTION borrar_producto(p_producto UUID) RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE v_lotes UUID[];
BEGIN
    IF NOT EXISTS (SELECT 1 FROM productos
                   WHERE id_producto = p_producto AND id_distribuidor = usuario_actual()) THEN
        RAISE EXCEPTION 'Producto no encontrado';
    END IF;
    IF EXISTS (SELECT 1 FROM detalle_pedidos WHERE producto_id = p_producto) THEN
        RAISE EXCEPTION 'El producto tiene pedidos asociados; desactívalo en lugar de borrarlo';
    END IF;
    SELECT ARRAY_AGG(stock_id) INTO v_lotes FROM productos_stock WHERE id_producto = p_producto;
    DELETE FROM productos_stock WHERE id_producto = p_producto;
    IF v_lotes IS NOT NULL THEN DELETE FROM stock WHERE id_stock = ANY (v_lotes); END IF;
    DELETE FROM productos WHERE id_producto = p_producto;
END $$;

-- C5. Crear pedido. p_items = '[{"producto_id":"<uuid>","cantidad":3}, ...]'
--     Descuenta por FEFO (primero el lote que caduca antes), ignora lotes caducados,
--     congela el precio y crea los pagos. Con la misma p_clave devuelve el pedido ya creado.
CREATE OR REPLACE FUNCTION crear_pedido(p_distribuidor UUID, p_direccion TEXT, p_items JSONB,
                                        p_clave UUID DEFAULT NULL)
RETURNS UUID
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
    v_cliente  UUID := usuario_actual();
    v_dist     distribuidores%ROWTYPE;
    v_pedido   UUID;
    v_total    NUMERIC(12,2) := 0;
    v_anticipo NUMERIC(10,2);
    v_ref      TEXT;
    v_precio   NUMERIC(10,2);
    v_nombre   TEXT;
    v_resta    INT;
    v_toma     INT;
    it         RECORD;
    lote       RECORD;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM clientes WHERE id_cliente = v_cliente) THEN
        RAISE EXCEPTION 'Solo un cliente autenticado puede crear pedidos';
    END IF;

    IF p_clave IS NOT NULL THEN
        SELECT id_pedido INTO v_pedido FROM pedidos
        WHERE cliente_id = v_cliente AND clave_idempotencia = p_clave;
        IF FOUND THEN RETURN v_pedido; END IF;
    END IF;

    SELECT * INTO v_dist FROM distribuidores WHERE id_distribuidor = p_distribuidor;
    IF NOT FOUND THEN RAISE EXCEPTION 'El distribuidor no existe'; END IF;
    IF v_dist.clabe IS NULL THEN
        RAISE EXCEPTION 'Este distribuidor aún no ha capturado sus datos bancarios';
    END IF;
    IF p_direccion IS NULL OR TRIM(p_direccion) = '' THEN
        RAISE EXCEPTION 'La dirección de entrega es obligatoria';
    END IF;
    IF p_items IS NULL OR jsonb_typeof(p_items) <> 'array' OR jsonb_array_length(p_items) = 0 THEN
        RAISE EXCEPTION 'El pedido debe incluir al menos un producto';
    END IF;

    INSERT INTO pedidos (cliente_id, distribuidor_id, direccion_entrega, clave_idempotencia)
    VALUES (v_cliente, p_distribuidor, TRIM(p_direccion), p_clave)
    RETURNING id_pedido INTO v_pedido;

    -- Un producto repetido se suma en una línea; orden fijo para evitar interbloqueos
    FOR it IN
        SELECT (x->>'producto_id')::uuid AS producto_id, SUM((x->>'cantidad')::int) AS cantidad
        FROM jsonb_array_elements(p_items) x GROUP BY 1 ORDER BY 1
    LOOP
        IF it.cantidad <= 0 THEN RAISE EXCEPTION 'Las cantidades deben ser mayores a 0'; END IF;

        SELECT precio_unitario, nombre INTO v_precio, v_nombre
        FROM productos
        WHERE id_producto = it.producto_id AND id_distribuidor = p_distribuidor AND activo;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'El producto % no está disponible con este distribuidor', it.producto_id;
        END IF;

        INSERT INTO detalle_pedidos (pedido_id, producto_id, cantidad, precio_unitario)
        VALUES (v_pedido, it.producto_id, it.cantidad, v_precio);

        v_resta := it.cantidad;
        FOR lote IN
            SELECT s.id_stock, s.stock
            FROM stock s JOIN productos_stock ps ON ps.stock_id = s.id_stock
            WHERE ps.id_producto = it.producto_id AND s.stock > 0 AND s.caducidad > CURRENT_TIMESTAMP
            ORDER BY s.caducidad, ps.fecha_registro
            FOR UPDATE OF s
        LOOP
            EXIT WHEN v_resta = 0;
            v_toma := LEAST(v_resta, lote.stock);
            UPDATE stock SET stock = stock - v_toma WHERE id_stock = lote.id_stock;
            INSERT INTO detalle_pedido_lotes (pedido_id, producto_id, stock_id, cantidad)
            VALUES (v_pedido, it.producto_id, lote.id_stock, v_toma);
            v_resta := v_resta - v_toma;
        END LOOP;

        IF v_resta > 0 THEN
            RAISE EXCEPTION 'Stock insuficiente para "%" (faltan % unidades)', v_nombre, v_resta;
        END IF;
        v_total := v_total + it.cantidad * v_precio;
    END LOOP;

    UPDATE pedidos SET total = v_total WHERE id_pedido = v_pedido;

    v_anticipo := LEAST(v_total, GREATEST(0.01, ROUND(v_total * v_dist.porcentaje_anticipo / 100, 2)));
    v_ref := 'SFY-' || UPPER(LEFT(REPLACE(v_pedido::text, '-', ''), 8));
    INSERT INTO pagos (pedido_id, tipo, monto, referencia)
    VALUES (v_pedido, 'ANTICIPO', v_anticipo, v_ref || '-A');
    IF v_total - v_anticipo > 0 THEN
        INSERT INTO pagos (pedido_id, tipo, monto, referencia)
        VALUES (v_pedido, 'FINAL', v_total - v_anticipo, v_ref || '-F');
    END IF;

    RETURN v_pedido;
END $$;

-- C6. Datos para transferir (banco, titular, CLABE, monto, referencia): solo el cliente del pedido
CREATE OR REPLACE FUNCTION datos_bancarios_pedido(p_pedido UUID)
RETURNS TABLE (banco TEXT, titular TEXT, clabe TEXT, tipo TEXT, monto NUMERIC, referencia TEXT, estado TEXT)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT d.banco::text, d.titular::text, d.clabe::text, pg.tipo::text,
           pg.monto, pg.referencia::text, pg.estado::text
    FROM pedidos p
    JOIN distribuidores d ON d.id_distribuidor = p.distribuidor_id
    JOIN pagos pg ON pg.pedido_id = p.id_pedido
    WHERE p.id_pedido = p_pedido AND p.cliente_id = usuario_actual()
    ORDER BY pg.tipo
$$;

-- C7. Cliente adjunta comprobante (también para volver a subir uno rechazado).
--     El archivo va a Storage; aquí solo se guarda la ruta (JPG, PNG o PDF).
CREATE OR REPLACE FUNCTION subir_comprobante(p_pedido UUID, p_tipo TEXT, p_url TEXT) RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE v_ped pedidos%ROWTYPE;
BEGIN
    SELECT * INTO v_ped FROM pedidos WHERE id_pedido = p_pedido FOR UPDATE;
    IF NOT FOUND OR v_ped.cliente_id IS DISTINCT FROM usuario_actual() THEN
        RAISE EXCEPTION 'Pedido no encontrado';
    END IF;
    IF p_url IS NULL OR p_url !~* '\.(jpe?g|png|pdf)(\?.*)?$' THEN
        RAISE EXCEPTION 'Archivo inválido: solo JPG, PNG o PDF';
    END IF;

    IF p_tipo = 'ANTICIPO' THEN
        IF v_ped.estatus <> 'PENDIENTE' THEN
            RAISE EXCEPTION 'Solo se puede adjuntar el comprobante del anticipo en pedidos PENDIENTES';
        END IF;
    ELSIF p_tipo = 'FINAL' THEN
        IF v_ped.estatus NOT IN ('EN_PROCESO','EN_ENVIO') THEN
            RAISE EXCEPTION 'El pago final se adjunta cuando el pedido está EN_PROCESO o EN_ENVIO';
        END IF;
    ELSE
        RAISE EXCEPTION 'Tipo de pago inválido';
    END IF;

    UPDATE pagos SET estado = 'POR_VALIDAR', metodo = 'TRANSFERENCIA', comprobante_url = p_url,
                     fecha_comprobante = CURRENT_TIMESTAMP, motivo_rechazo = NULL, fecha_validacion = NULL
    WHERE pedido_id = p_pedido AND tipo = p_tipo AND estado IN ('PENDIENTE','RECHAZADO');
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No hay un pago % pendiente de comprobante en este pedido', p_tipo;
    END IF;

    IF p_tipo = 'ANTICIPO' THEN
        UPDATE pedidos SET estatus = 'POR_VALIDAR' WHERE id_pedido = p_pedido;
    END IF;
END $$;

-- C8. Proveedor valida (o rechaza) el comprobante del anticipo.
--     Al aprobar fija la fecha estimada de entrega (la decide el proveedor).
CREATE OR REPLACE FUNCTION validar_anticipo(p_pedido UUID, p_aprobado BOOLEAN,
                                            p_fecha_entrega_estimada TIMESTAMPTZ DEFAULT NULL,
                                            p_motivo TEXT DEFAULT NULL) RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE v_ped pedidos%ROWTYPE;
BEGIN
    SELECT * INTO v_ped FROM pedidos WHERE id_pedido = p_pedido FOR UPDATE;
    IF NOT FOUND OR v_ped.distribuidor_id IS DISTINCT FROM usuario_actual() THEN
        RAISE EXCEPTION 'Pedido no encontrado';
    END IF;
    IF v_ped.estatus <> 'POR_VALIDAR' THEN
        RAISE EXCEPTION 'El pedido no está pendiente de validación';
    END IF;

    IF p_aprobado THEN
        IF p_fecha_entrega_estimada IS NULL OR p_fecha_entrega_estimada <= CURRENT_TIMESTAMP THEN
            RAISE EXCEPTION 'Indica una fecha estimada de entrega futura';
        END IF;
        UPDATE pagos SET estado = 'CONFIRMADO', fecha_validacion = CURRENT_TIMESTAMP
        WHERE pedido_id = p_pedido AND tipo = 'ANTICIPO' AND estado = 'POR_VALIDAR';
        UPDATE pedidos SET estatus = 'EN_PROCESO', fecha_entrega_estimada = p_fecha_entrega_estimada
        WHERE id_pedido = p_pedido;
    ELSE
        IF p_motivo IS NULL OR TRIM(p_motivo) = '' THEN
            RAISE EXCEPTION 'Indica el motivo del rechazo';
        END IF;
        UPDATE pagos SET estado = 'RECHAZADO', motivo_rechazo = p_motivo,
                         fecha_validacion = CURRENT_TIMESTAMP
        WHERE pedido_id = p_pedido AND tipo = 'ANTICIPO' AND estado = 'POR_VALIDAR';
        UPDATE pedidos SET estatus = 'PENDIENTE' WHERE id_pedido = p_pedido;
    END IF;
END $$;

-- C9. Proveedor registra/confirma el pago final (efectivo al entregar, o transferencia con comprobante)
CREATE OR REPLACE FUNCTION confirmar_pago_final(p_pedido UUID, p_metodo TEXT DEFAULT 'EFECTIVO',
                                                p_aprobado BOOLEAN DEFAULT TRUE,
                                                p_motivo TEXT DEFAULT NULL) RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE v_ped pedidos%ROWTYPE;
BEGIN
    SELECT * INTO v_ped FROM pedidos WHERE id_pedido = p_pedido FOR UPDATE;
    IF NOT FOUND OR v_ped.distribuidor_id IS DISTINCT FROM usuario_actual() THEN
        RAISE EXCEPTION 'Pedido no encontrado';
    END IF;
    IF v_ped.estatus NOT IN ('EN_PROCESO','EN_ENVIO') THEN
        RAISE EXCEPTION 'El pago final se registra con el pedido EN_PROCESO o EN_ENVIO';
    END IF;

    IF p_metodo = 'EFECTIVO' THEN
        UPDATE pagos SET estado = 'CONFIRMADO', metodo = 'EFECTIVO', fecha_validacion = CURRENT_TIMESTAMP
        WHERE pedido_id = p_pedido AND tipo = 'FINAL' AND estado IN ('PENDIENTE','POR_VALIDAR','RECHAZADO');
    ELSIF p_aprobado THEN
        UPDATE pagos SET estado = 'CONFIRMADO', fecha_validacion = CURRENT_TIMESTAMP
        WHERE pedido_id = p_pedido AND tipo = 'FINAL' AND estado = 'POR_VALIDAR';
    ELSE
        IF p_motivo IS NULL OR TRIM(p_motivo) = '' THEN
            RAISE EXCEPTION 'Indica el motivo del rechazo';
        END IF;
        UPDATE pagos SET estado = 'RECHAZADO', motivo_rechazo = p_motivo, fecha_validacion = CURRENT_TIMESTAMP
        WHERE pedido_id = p_pedido AND tipo = 'FINAL' AND estado = 'POR_VALIDAR';
    END IF;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No hay un pago final por confirmar en este pedido';
    END IF;
END $$;

-- C10. Proveedor avanza el pedido: EN_PROCESO -> EN_ENVIO -> ENTREGADO
CREATE OR REPLACE FUNCTION avanzar_pedido(p_pedido UUID, p_nuevo_estatus TEXT) RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
    IF p_nuevo_estatus NOT IN ('EN_ENVIO','ENTREGADO') THEN
        RAISE EXCEPTION 'Esta función solo avanza a EN_ENVIO o ENTREGADO';
    END IF;
    UPDATE pedidos SET estatus = p_nuevo_estatus
    WHERE id_pedido = p_pedido AND distribuidor_id = usuario_actual();
    IF NOT FOUND THEN RAISE EXCEPTION 'Pedido no encontrado'; END IF;
END $$;

-- C11. Cancelar: el actor se deduce de quién es el usuario autenticado.
--      Cliente: PENDIENTE / POR_VALIDAR / EN_PROCESO.
--      Proveedor ("rechazar pedido"): POR_VALIDAR / EN_PROCESO, con motivo obligatorio.
--      En ambos casos un pago ya confirmado NO se reembolsa (el sistema no maneja reembolsos).
CREATE OR REPLACE FUNCTION cancelar_pedido(p_pedido UUID, p_motivo TEXT DEFAULT NULL) RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE v_ped pedidos%ROWTYPE; v_actor TEXT;
BEGIN
    SELECT * INTO v_ped FROM pedidos WHERE id_pedido = p_pedido FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Pedido no encontrado'; END IF;

    IF v_ped.cliente_id = usuario_actual() THEN v_actor := 'CLIENTE';
    ELSIF v_ped.distribuidor_id = usuario_actual() THEN v_actor := 'PROVEEDOR';
    ELSE RAISE EXCEPTION 'Pedido no encontrado';
    END IF;

    IF v_actor = 'PROVEEDOR' AND (p_motivo IS NULL OR TRIM(p_motivo) = '') THEN
        RAISE EXCEPTION 'Indica el motivo por el que rechazas el pedido';
    END IF;

    UPDATE pedidos SET estatus = 'CANCELADO', cancelado_por = v_actor, motivo_cancelacion = p_motivo
    WHERE id_pedido = p_pedido;
END $$;

-- C12. Tarea programada: cancela pedidos sin comprobante pasado el plazo (por defecto 24 h).
--      El plazo cuenta desde la creación o desde el último rechazo de comprobante.
--      Ej. con pg_cron: SELECT cron.schedule('0 * * * *', 'SELECT cancelar_pedidos_vencidos()');
CREATE OR REPLACE FUNCTION cancelar_pedidos_vencidos(p_plazo INTERVAL DEFAULT INTERVAL '24 hours')
RETURNS INT
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE n INT;
BEGIN
    UPDATE pedidos SET estatus = 'CANCELADO', cancelado_por = 'SISTEMA',
                       motivo_cancelacion = 'No se adjuntó comprobante dentro del plazo'
    WHERE estatus = 'PENDIENTE'
      AND EXISTS (SELECT 1 FROM pagos pg
                  WHERE pg.pedido_id = pedidos.id_pedido AND pg.tipo = 'ANTICIPO'
                    AND COALESCE(pg.fecha_validacion, pg.fecha_creacion) < CURRENT_TIMESTAMP - p_plazo);
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN n;
END $$;
