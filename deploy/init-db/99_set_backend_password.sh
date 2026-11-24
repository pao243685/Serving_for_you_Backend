#!/bin/bash
# Se ejecuta UNA sola vez, al crear la BD (volumen vacío).
#
# Crea el usuario con el que se conecta el backend (app_backend) y fija su contraseña
# con APP_BACKEND_PASSWORD (la contraseña nunca va en el repositorio).
#
# - Esquema actual (db/squema-1.0.0.sql, el que usa el código hoy): app_backend no existe,
#   se crea con permisos de lectura/escritura sobre las tablas (sin ser dueño ni superusuario).
# - Esquema v3 (db/02_roles.sql ya creó app_backend NOINHERIT): solo se fija la contraseña.
set -euo pipefail

psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v pw="$APP_BACKEND_PASSWORD" <<'SQL'
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_backend') THEN
        CREATE ROLE app_backend LOGIN;
    END IF;
    -- Esquema actual (sin los roles del v3): permisos de lectura/escritura sobre las tablas
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_cliente') THEN
        GRANT USAGE ON SCHEMA public TO app_backend;
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_backend;
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_backend;
        GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO app_backend;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_backend;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
            GRANT USAGE, SELECT ON SEQUENCES TO app_backend;
    END IF;
END $$;

ALTER ROLE app_backend PASSWORD :'pw';
SQL
