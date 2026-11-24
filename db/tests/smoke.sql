-- =====================================================================
-- Pruebas de humo de la BD (las ejecuta el CI sobre un Postgres limpio).
-- Cubre: flujo completo de pedido, FEFO, cancelaciones, bloqueos de
-- seguridad (permisos y RLS) y cancelación automática.
-- Todo corre dentro de una transacción que se revierte al final.
-- Falla (exit code != 0) si cualquier comprobación no se cumple.
-- =====================================================================
\set ON_ERROR_STOP on
BEGIN;

CREATE FUNCTION t_ok(cond BOOLEAN, msg TEXT) RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN
    IF cond IS NOT TRUE THEN RAISE EXCEPTION 'FALLO: %', msg; END IF;
END $$;

-- Ejecuta una sentencia que DEBE fallar; si no falla, la prueba falla
CREATE FUNCTION t_error(p_sql TEXT, msg TEXT) RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN
    BEGIN
        EXECUTE p_sql;
    EXCEPTION WHEN OTHERS THEN
        RETURN;
    END;
    RAISE EXCEPTION 'FALLO (se esperaba un error): %', msg;
END $$;

DO $$
DECLARE
    da  UUID := 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';   -- distribuidor con banco
    db_ UUID := 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb';   -- distribuidor SIN banco
    c1  UUID := 'c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1';
    c2  UUID := 'c2c2c2c2-c2c2-c2c2-c2c2-c2c2c2c2c2c2';
    prod UUID; prod_b UUID; p1 UUID; p2 UUID; p3 UUID; n INT; v TEXT;
BEGIN
    ---------------------------------------------------------------- 1. registro
    SET LOCAL ROLE app_auth;
    INSERT INTO distribuidores (id_distribuidor, nombre_marca, nombre_encargado, correo, contrasena,
                                telefono, direccion_local, terminos_condiciones, banco, titular, clabe)
    VALUES (da, 'Dulce A', 'Ana', 'ANA@Mail.COM', 'argon2-hash', '9611111111', 'Calle 1', TRUE,
            'BBVA', 'Ana', '111111111111111111');
    INSERT INTO distribuidores (id_distribuidor, nombre_marca, nombre_encargado, correo, contrasena,
                                telefono, direccion_local, terminos_condiciones)
    VALUES (db_, 'Dulce B', 'Beto', 'beto@mail.com', 'argon2-hash', '9622222222', 'Calle 2', TRUE);
    INSERT INTO clientes (id_cliente, nombre, correo, contrasena, telefono)
    VALUES (c1, 'Cafe 1', 'c1@mail.com', 'argon2-hash', '9633333333'),
           (c2, 'Cafe 2', 'c2@mail.com', 'argon2-hash', '9644444444');
    SELECT correo INTO v FROM distribuidores WHERE id_distribuidor = da;
    PERFORM t_ok(v = 'ana@mail.com', 'el correo debe guardarse en minúsculas');
    PERFORM t_error($q$INSERT INTO clientes(nombre,correo,contrasena,telefono)
                       VALUES('X','C1@MAIL.COM','x','9655555555')$q$, 'correo duplicado');
    RESET ROLE;

    ---------------------------------------------------------------- 2. catálogo y lotes
    SET LOCAL ROLE app_distribuidor;
    PERFORM set_config('app.usuario_id', da::text, true);
    prod := registrar_producto('Pastel','KG',NULL,100,'a.jpg','Pasteles','rico',5, now() + interval '10 days');
    PERFORM t_error($q$SELECT registrar_producto('pastel ','KG',NULL,100,'a.jpg','Pasteles','dup',5, now()+interval '10 days')$q$,
                    'producto duplicado (mismo nombre, unidad y tamaño)');
    PERFORM t_error($q$SELECT registrar_producto('Flan','PZ',NULL,20,'f.jpg','Gelatinas y Flanes','x',5, now()-interval '1 day')$q$,
                    'lote con caducidad pasada');
    PERFORM reabastecer_stock(prod, 5, now() + interval '3 days');
    PERFORM t_error($q$UPDATE distribuidores SET correo = 'hack@x.com'$q$, 'el distribuidor no puede cambiar su correo');
    PERFORM set_config('app.usuario_id', db_::text, true);
    prod_b := registrar_producto('Galleta','PZ','GRANDE',10,'g.jpg','Galletas','x',50, now() + interval '20 days');
    RESET ROLE;

    ---------------------------------------------------------------- 3. crear pedido
    SET LOCAL ROLE app_cliente;
    PERFORM set_config('app.usuario_id', c1::text, true);
    PERFORM t_error(format($q$SELECT crear_pedido(%L,'Av 1',%L::jsonb)$q$, db_,
                    jsonb_build_array(jsonb_build_object('producto_id', prod_b, 'cantidad', 1))::text),
                    'pedido a un distribuidor sin datos bancarios');
    PERFORM t_error(format($q$SELECT crear_pedido(%L,'Av 1',%L::jsonb)$q$, da,
                    jsonb_build_array(jsonb_build_object('producto_id', prod, 'cantidad', 100))::text),
                    'pedido con stock insuficiente');
    p1 := crear_pedido(da, 'Av 1', jsonb_build_array(jsonb_build_object('producto_id', prod, 'cantidad', 7)),
                       '11111111-1111-1111-1111-111111111111');
    PERFORM t_ok(p1 = crear_pedido(da, 'Av 1', jsonb_build_array(jsonb_build_object('producto_id', prod, 'cantidad', 7)),
                       '11111111-1111-1111-1111-111111111111'), 'idempotencia: misma clave, mismo pedido');
    SELECT total INTO STRICT v FROM pedidos WHERE id_pedido = p1;
    PERFORM t_ok(v::numeric = 700, 'total = 7 x 100');
    SELECT monto INTO STRICT v FROM pagos WHERE pedido_id = p1 AND tipo = 'ANTICIPO';
    PERFORM t_ok(v::numeric = 350, 'anticipo = 50 %');
    RESET ROLE;
    -- FEFO: primero se vacía el lote que caduca antes (5) y se toman 2 del otro
    SELECT string_agg(s.stock::text, ',' ORDER BY s.caducidad) INTO v
    FROM stock s JOIN productos_stock ps ON ps.stock_id = s.id_stock WHERE ps.id_producto = prod;
    PERFORM t_ok(v = '0,3', format('FEFO: se esperaba 0,3 y hay %s', v));

    ---------------------------------------------------------------- 4. flujo de pago y estatus
    SET LOCAL ROLE app_cliente;
    PERFORM set_config('app.usuario_id', c1::text, true);
    PERFORM t_error(format($q$SELECT subir_comprobante(%L,'ANTICIPO','virus.exe')$q$, p1), 'comprobante con formato inválido');
    PERFORM subir_comprobante(p1, 'ANTICIPO', 'comp.png');
    RESET ROLE;
    SET LOCAL ROLE app_distribuidor;
    PERFORM set_config('app.usuario_id', da::text, true);
    PERFORM validar_anticipo(p1, FALSE, NULL, 'monto no coincide');
    SELECT estatus INTO STRICT v FROM pedidos WHERE id_pedido = p1;
    PERFORM t_ok(v = 'PENDIENTE', 'comprobante rechazado: el pedido vuelve a PENDIENTE');
    RESET ROLE;
    SET LOCAL ROLE app_cliente;
    PERFORM set_config('app.usuario_id', c1::text, true);
    PERFORM subir_comprobante(p1, 'ANTICIPO', 'comp2.pdf');
    RESET ROLE;
    SET LOCAL ROLE app_distribuidor;
    PERFORM set_config('app.usuario_id', da::text, true);
    PERFORM t_error(format($q$SELECT validar_anticipo(%L, TRUE, NULL)$q$, p1), 'aprobar sin fecha de entrega');
    PERFORM validar_anticipo(p1, TRUE, now() + interval '2 days');
    PERFORM t_error(format($q$SELECT avanzar_pedido(%L,'ENTREGADO')$q$, p1), 'saltar de EN_PROCESO a ENTREGADO');
    PERFORM avanzar_pedido(p1, 'EN_ENVIO');
    PERFORM t_error(format($q$SELECT avanzar_pedido(%L,'ENTREGADO')$q$, p1), 'entregar sin pago final confirmado');
    PERFORM confirmar_pago_final(p1);
    PERFORM avanzar_pedido(p1, 'ENTREGADO');
    SELECT estatus INTO STRICT v FROM pedidos WHERE id_pedido = p1;
    PERFORM t_ok(v = 'ENTREGADO', 'el pedido llega a ENTREGADO');
    PERFORM t_error(format($q$SELECT cancelar_pedido(%L,'x')$q$, p1), 'cancelar un pedido ENTREGADO');
    SELECT count(*) INTO n FROM pedido_historial WHERE pedido_id = p1;
    PERFORM t_ok(n >= 6, 'la bitácora registra los cambios de estatus');
    RESET ROLE;

    ---------------------------------------------------------------- 5. cancelaciones (sin reembolsos)
    SET LOCAL ROLE app_cliente;
    PERFORM set_config('app.usuario_id', c2::text, true);
    p2 := crear_pedido(da, 'Av 2', jsonb_build_array(jsonb_build_object('producto_id', prod, 'cantidad', 2)));
    p3 := crear_pedido(da, 'Av 3', jsonb_build_array(jsonb_build_object('producto_id', prod, 'cantidad', 1)));
    PERFORM subir_comprobante(p2, 'ANTICIPO', 'b.jpg');
    PERFORM subir_comprobante(p3, 'ANTICIPO', 'c.jpg');
    RESET ROLE;
    SET LOCAL ROLE app_distribuidor;
    PERFORM set_config('app.usuario_id', da::text, true);
    PERFORM validar_anticipo(p2, TRUE, now() + interval '2 days');
    PERFORM validar_anticipo(p3, TRUE, now() + interval '2 days');
    PERFORM t_error(format($q$SELECT cancelar_pedido(%L)$q$, p3), 'el proveedor cancela sin motivo');
    PERFORM cancelar_pedido(p3, 'sin capacidad de entrega');
    RESET ROLE;
    SET LOCAL ROLE app_cliente;
    PERFORM set_config('app.usuario_id', c2::text, true);
    PERFORM cancelar_pedido(p2, 'ya no lo necesito');
    RESET ROLE;
    SELECT count(*) INTO n FROM pagos WHERE pedido_id IN (p2, p3) AND tipo = 'ANTICIPO' AND estado = 'CONFIRMADO';
    PERFORM t_ok(n = 2, 'el anticipo confirmado se conserva (no hay reembolsos)');
    SELECT count(*) INTO n FROM pagos WHERE pedido_id IN (p2, p3) AND tipo = 'FINAL' AND estado = 'ANULADO';
    PERFORM t_ok(n = 2, 'el pago final pendiente se anula');
    SELECT sum(stock) INTO v FROM stock s JOIN productos_stock ps ON ps.stock_id = s.id_stock WHERE ps.id_producto = prod;
    PERFORM t_ok(v::int = 3, format('el stock cancelado vuelve a su lote (esperado 3, hay %s)', v));

    ---------------------------------------------------------------- 6. seguridad
    SET LOCAL ROLE app_cliente;
    PERFORM set_config('app.usuario_id', c1::text, true);
    PERFORM t_error('SELECT contrasena FROM distribuidores', 'el cliente no puede leer la tabla distribuidores');
    PERFORM t_error($q$UPDATE pedidos SET estatus = 'ENTREGADO'$q$, 'el cliente no puede modificar pedidos directo');
    PERFORM t_error($q$INSERT INTO pedidos(cliente_id,distribuidor_id,direccion_entrega) VALUES (gen_random_uuid(),gen_random_uuid(),'x')$q$,
                    'el cliente no puede insertar pedidos directo');
    PERFORM t_error('SELECT * FROM stock', 'el cliente no puede leer lotes');
    PERFORM t_error('SELECT * FROM detalle_pedido_lotes', 'nadie lee detalle_pedido_lotes directo');
    SELECT count(*) INTO n FROM clientes;
    PERFORM t_ok(n = 1, 'el cliente solo ve su propio registro');
    SELECT count(*) INTO n FROM pedidos;
    PERFORM t_ok(n = 1, 'el cliente 1 solo ve su pedido');
    PERFORM t_ok((SELECT count(*) FROM distribuidores_publico) = 2, 'el cliente ve los distribuidores por la vista pública');
    PERFORM set_config('app.usuario_id', c2::text, true);
    SELECT count(*) INTO n FROM datos_bancarios_pedido(p1);
    PERFORM t_ok(n = 0, 'el cliente 2 no ve datos bancarios del pedido del cliente 1');
    PERFORM t_error(format($q$SELECT cancelar_pedido(%L)$q$, p1), 'el cliente 2 cancela un pedido ajeno');
    RESET ROLE;
    SET LOCAL ROLE app_distribuidor;
    PERFORM set_config('app.usuario_id', db_::text, true);
    SELECT count(*) INTO n FROM pedidos;
    PERFORM t_ok(n = 0, 'el distribuidor B no ve pedidos de A');
    SELECT count(*) INTO n FROM stock;
    PERFORM t_ok(n = 1, 'el distribuidor B solo ve su propio lote');
    UPDATE distribuidores SET clabe = '999999999999999999' WHERE id_distribuidor = da;
    GET DIAGNOSTICS n = ROW_COUNT;
    PERFORM t_ok(n = 0, 'el distribuidor B no puede cambiar la CLABE de A');
    PERFORM t_error('SELECT contrasena FROM clientes', 'el distribuidor no lee contraseñas de clientes');
    PERFORM t_error(format($q$SELECT borrar_producto(%L)$q$, prod), 'borrar un producto de otro distribuidor');
    RESET ROLE;
    SET ROLE app_backend;
    PERFORM t_error('SELECT * FROM pedidos', 'app_backend no toca tablas por sí mismo');
    RESET ROLE;

    ---------------------------------------------------------------- 7. cancelación automática
    SET LOCAL ROLE app_cliente;
    PERFORM set_config('app.usuario_id', c1::text, true);
    p2 := crear_pedido(da, 'Av 4', jsonb_build_array(jsonb_build_object('producto_id', prod, 'cantidad', 2)));
    RESET ROLE;
    -- dentro de una transacción el reloj no avanza: se simula que el pedido tiene 25 h sin comprobante
    UPDATE pagos SET fecha_creacion = now() - interval '25 hours' WHERE pedido_id = p2;
    SET LOCAL ROLE app_sistema;
    PERFORM t_ok(cancelar_pedidos_vencidos('48 hours') = 0, 'no cancela antes del plazo');
    PERFORM t_ok(cancelar_pedidos_vencidos('24 hours') = 1, 'cancela pasado el plazo');
    RESET ROLE;
    SELECT cancelado_por INTO v FROM pedidos WHERE id_pedido = p2;
    PERFORM t_ok(v = 'SISTEMA', 'cancelado por el sistema');

    RAISE NOTICE 'TODAS LAS PRUEBAS DE LA BD PASARON';
END $$;

ROLLBACK;
