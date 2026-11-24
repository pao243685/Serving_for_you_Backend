-- =====================================================================
-- Serving for you – 04_permisos_rls.sql (v3)
-- Principio: mínimo privilegio. Cada rol ve solo lo suyo y no escribe directo
-- lo que debe pasar por una función (pedidos, pagos, lotes).
-- Ejecutar DESPUÉS de 01, 02 y 03.
-- =====================================================================

GRANT USAGE ON SCHEMA public TO app_cliente, app_distribuidor, app_auth, app_sistema;

-- Nadie hereda permisos por defecto: se parte de cero
REVOKE ALL ON ALL TABLES    IN SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;

-- ---------------------------------------------------------------------
-- 1. Activar RLS en todas las tablas
--    (las funciones SECURITY DEFINER son del dueño, que no está sujeto a RLS)
-- ---------------------------------------------------------------------
ALTER TABLE distribuidores        ENABLE ROW LEVEL SECURITY;
ALTER TABLE clientes              ENABLE ROW LEVEL SECURITY;
ALTER TABLE productos             ENABLE ROW LEVEL SECURITY;
ALTER TABLE stock                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE productos_stock       ENABLE ROW LEVEL SECURITY;
ALTER TABLE pedidos               ENABLE ROW LEVEL SECURITY;
ALTER TABLE detalle_pedidos       ENABLE ROW LEVEL SECURITY;
ALTER TABLE detalle_pedido_lotes  ENABLE ROW LEVEL SECURITY;   -- sin políticas: solo funciones
ALTER TABLE pagos                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE pedido_historial      ENABLE ROW LEVEL SECURITY;
ALTER TABLE pago_historial        ENABLE ROW LEVEL SECURITY;

-- ---------------------------------------------------------------------
-- 2. app_auth: solo registro e inicio de sesión
-- ---------------------------------------------------------------------
GRANT SELECT, INSERT ON distribuidores, clientes TO app_auth;
GRANT EXECUTE ON FUNCTION usuario_actual() TO app_auth;

CREATE POLICY auth_lee_distribuidores ON distribuidores FOR SELECT TO app_auth USING (TRUE);
CREATE POLICY auth_crea_distribuidores ON distribuidores FOR INSERT TO app_auth WITH CHECK (TRUE);
CREATE POLICY auth_lee_clientes ON clientes FOR SELECT TO app_auth USING (TRUE);
CREATE POLICY auth_crea_clientes ON clientes FOR INSERT TO app_auth WITH CHECK (TRUE);

-- ---------------------------------------------------------------------
-- 3. app_distribuidor
-- ---------------------------------------------------------------------
GRANT EXECUTE ON FUNCTION usuario_actual() TO app_distribuidor;

-- Su perfil: puede cambiar sus datos y los bancarios, nunca el correo ni los términos
GRANT SELECT ON distribuidores TO app_distribuidor;
GRANT UPDATE (nombre_marca, nombre_encargado, telefono, direccion_local, contrasena,
              banco, titular, clabe, porcentaje_anticipo) ON distribuidores TO app_distribuidor;
CREATE POLICY dist_su_perfil ON distribuidores FOR ALL TO app_distribuidor
    USING (id_distribuidor = usuario_actual()) WITH CHECK (id_distribuidor = usuario_actual());

-- Solo ve nombre y teléfono de los clientes que le han hecho pedidos
GRANT SELECT (id_cliente, nombre, telefono) ON clientes TO app_distribuidor;
CREATE POLICY dist_ve_sus_clientes ON clientes FOR SELECT TO app_distribuidor
    USING (EXISTS (SELECT 1 FROM pedidos p
                   WHERE p.cliente_id = clientes.id_cliente AND p.distribuidor_id = usuario_actual()));

-- Catálogo propio (sin DELETE: se desactiva con activo = false o con borrar_producto())
GRANT SELECT, INSERT ON productos TO app_distribuidor;
GRANT UPDATE (nombre, imagen_url, precio_unitario, categoria, descripcion_producto, activo)
      ON productos TO app_distribuidor;
CREATE POLICY dist_sus_productos ON productos FOR ALL TO app_distribuidor
    USING (id_distribuidor = usuario_actual()) WITH CHECK (id_distribuidor = usuario_actual());

-- Lotes: ve y ajusta los suyos. Crear/borrar lotes: reabastecer_stock() / borrar_lote()
GRANT SELECT ON productos_stock TO app_distribuidor;
GRANT SELECT ON stock TO app_distribuidor;
GRANT UPDATE (stock, caducidad) ON stock TO app_distribuidor;
CREATE POLICY dist_sus_productos_stock ON productos_stock FOR SELECT TO app_distribuidor
    USING (id_producto IN (SELECT id_producto FROM productos WHERE id_distribuidor = usuario_actual()));
CREATE POLICY dist_sus_lotes ON stock FOR ALL TO app_distribuidor
    USING (id_stock IN (SELECT stock_id FROM productos_stock))   -- productos_stock ya filtra por dueño
    WITH CHECK (id_stock IN (SELECT stock_id FROM productos_stock));

-- Pedidos y pagos: solo lectura. Los cambios se hacen con funciones (validar_anticipo, avanzar_pedido...)
GRANT SELECT ON pedidos, detalle_pedidos, pagos, pedido_historial, pago_historial TO app_distribuidor;
GRANT SELECT ON catalogo_disponible TO app_distribuidor;

GRANT EXECUTE ON FUNCTION
    registrar_producto(TEXT,TEXT,TEXT,NUMERIC,TEXT,categoria_postre,TEXT,INT,TIMESTAMPTZ,TEXT),
    reabastecer_stock(UUID,INT,TIMESTAMPTZ),
    borrar_lote(UUID),
    borrar_producto(UUID),
    validar_anticipo(UUID,BOOLEAN,TIMESTAMPTZ,TEXT),
    confirmar_pago_final(UUID,TEXT,BOOLEAN,TEXT),
    avanzar_pedido(UUID,TEXT),
    cancelar_pedido(UUID,TEXT)
  TO app_distribuidor;

-- ---------------------------------------------------------------------
-- 4. app_cliente
-- ---------------------------------------------------------------------
GRANT EXECUTE ON FUNCTION usuario_actual() TO app_cliente;

-- Su perfil (sin tocar el correo)
GRANT SELECT ON clientes TO app_cliente;
GRANT UPDATE (nombre, telefono, contrasena) ON clientes TO app_cliente;
CREATE POLICY cliente_su_perfil ON clientes FOR ALL TO app_cliente
    USING (id_cliente = usuario_actual()) WITH CHECK (id_cliente = usuario_actual());

-- Catálogo: solo vistas públicas (nunca la tabla distribuidores: tiene hashes y CLABE)
GRANT SELECT ON distribuidores_publico, catalogo_disponible TO app_cliente;
GRANT SELECT ON productos TO app_cliente;
CREATE POLICY cliente_ve_catalogo ON productos FOR SELECT TO app_cliente USING (activo);

-- Sus pedidos: solo lectura. Crear/cancelar/pagar: crear_pedido(), cancelar_pedido(), subir_comprobante()
GRANT SELECT ON pedidos, detalle_pedidos, pagos, pedido_historial, pago_historial TO app_cliente;

GRANT EXECUTE ON FUNCTION
    crear_pedido(UUID,TEXT,JSONB,UUID),
    datos_bancarios_pedido(UUID),
    subir_comprobante(UUID,TEXT,TEXT),
    cancelar_pedido(UUID,TEXT)
  TO app_cliente;

-- ---------------------------------------------------------------------
-- 5. Políticas de lectura de pedidos y lo que cuelga de ellos
-- ---------------------------------------------------------------------
CREATE POLICY cliente_ve_sus_pedidos ON pedidos FOR SELECT TO app_cliente
    USING (cliente_id = usuario_actual());
CREATE POLICY dist_ve_sus_pedidos ON pedidos FOR SELECT TO app_distribuidor
    USING (distribuidor_id = usuario_actual());

-- Lo que cuelga de un pedido es visible solo si el pedido es visible (pedidos ya filtra por rol)
CREATE POLICY ve_detalle ON detalle_pedidos FOR SELECT TO app_cliente, app_distribuidor
    USING (EXISTS (SELECT 1 FROM pedidos p WHERE p.id_pedido = detalle_pedidos.pedido_id));
CREATE POLICY ve_pagos ON pagos FOR SELECT TO app_cliente, app_distribuidor
    USING (EXISTS (SELECT 1 FROM pedidos p WHERE p.id_pedido = pagos.pedido_id));
CREATE POLICY ve_historial_pedido ON pedido_historial FOR SELECT TO app_cliente, app_distribuidor
    USING (EXISTS (SELECT 1 FROM pedidos p WHERE p.id_pedido = pedido_historial.pedido_id));
CREATE POLICY ve_historial_pago ON pago_historial FOR SELECT TO app_cliente, app_distribuidor
    USING (EXISTS (SELECT 1 FROM pagos g WHERE g.id_pago = pago_historial.pago_id));

-- ---------------------------------------------------------------------
-- 6. app_sistema: solo la tarea programada
-- ---------------------------------------------------------------------
GRANT EXECUTE ON FUNCTION cancelar_pedidos_vencidos(INTERVAL) TO app_sistema;
