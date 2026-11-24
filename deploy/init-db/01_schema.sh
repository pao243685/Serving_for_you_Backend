#!/bin/bash
# Se ejecuta UNA sola vez, al crear la BD (volumen vacío).
# Aplica el esquema que usa el código hoy (db/squema-1.0.0.sql) sobre la BD $POSTGRES_DB.
# Se omiten sus líneas "CREATE DATABASE propuesta; \c propuesta": aquí la BD ya existe.
set -euo pipefail
grep -v -E '^\s*(CREATE DATABASE|\\c)\b' /schema/squema-1.0.0.sql \
  | psql -v ON_ERROR_STOP=1 -q -U "$POSTGRES_USER" -d "$POSTGRES_DB"
