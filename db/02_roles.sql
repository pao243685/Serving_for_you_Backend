-- =====================================================================
-- Serving for you – 02_roles.sql (v3)
-- Idempotente: se puede ejecutar varias veces (no usa DROP ROLE).
--
-- Modelo de conexión:
--   El backend se conecta UNA sola vez con 'app_backend' (sin privilegios sobre tablas).
--   En cada petición, dentro de la transacción, hace:
--       SET LOCAL ROLE app_cliente;            -- o app_distribuidor / app_auth / app_sistema
--       SELECT set_config('app.usuario_id', '<uuid del JWT>', true);
--   Así los permisos y el RLS se aplican según quién hace la petición.
-- =====================================================================

DO $$
BEGIN
    -- Roles "de trabajo": no pueden iniciar sesión, solo se asumen con SET ROLE
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_cliente')      THEN CREATE ROLE app_cliente      NOLOGIN; END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_distribuidor') THEN CREATE ROLE app_distribuidor NOLOGIN; END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_auth')         THEN CREATE ROLE app_auth         NOLOGIN; END IF;  -- login y registro
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_sistema')      THEN CREATE ROLE app_sistema      NOLOGIN; END IF;  -- tareas programadas

    -- Único rol con login para el backend. NOINHERIT: por sí mismo no puede tocar nada.
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_backend') THEN
        CREATE ROLE app_backend LOGIN NOINHERIT;
    END IF;
END $$;

GRANT app_cliente, app_distribuidor, app_auth, app_sistema TO app_backend;

-- La contraseña NO va en el repositorio. Ejecútala a mano (o desde tu gestor de secretos):
--   ALTER ROLE app_backend PASSWORD '<contraseña larga y aleatoria>';
