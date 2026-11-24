#!/usr/bin/env bash
# Respalda los DATOS de la BD a S3 usando el rol de la instancia (LabInstanceProfile): sin claves.
# Programado con cron (ver la guía). Restauración: ver la guía, sección "Respaldos".
set -euo pipefail
export PATH="$PATH:/snap/bin"   # cron no incluye /snap/bin, donde está la AWS CLI
cd /opt/sfy

BUCKET="$(grep -E '^S3_BUCKET=' .env | head -n1 | cut -d= -f2- || true)"
if [ -z "${BUCKET}" ]; then echo "S3_BUCKET vacío: no se respalda"; exit 0; fi

FILE="serving_$(date -u +%Y%m%dT%H%M%SZ).sql.gz"
docker compose exec -T db pg_dump -U postgres -d serving --data-only --disable-triggers \
  | gzip | aws s3 cp - "s3://${BUCKET}/backups/${FILE}"
echo "Respaldo subido: s3://${BUCKET}/backups/${FILE}"
