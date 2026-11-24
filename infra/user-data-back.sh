#!/bin/bash
# user-data de la EC2 B (backend + Postgres). Corre como root UNA vez, al crear la instancia.
# crear-infra.sh reemplaza los marcadores __ALLOWED_ORIGINS__, __S3_BUCKET__ y __SETUP_B64__.
set -euxo pipefail
exec > >(tee -a /var/log/sfy-user-data.log) 2>&1

# deploy/setup-ec2.sh incrustado por crear-infra.sh (base64)
echo "__SETUP_B64__" | base64 -d > /root/setup-ec2.sh
bash /root/setup-ec2.sh back

# /opt/sfy/.env: los secretos se generan AQUÍ y nunca salen de la instancia
if [ ! -f /opt/sfy/.env ]; then
  umask 077
  cat > /opt/sfy/.env <<ENV
DOCKERHUB_USER=pendiente     # lo fija el pipeline en el primer despliegue
BACKEND_TAG=latest           # lo actualiza deploy.sh en cada despliegue
POSTGRES_PASSWORD=$(openssl rand -hex 24)
APP_BACKEND_PASSWORD=$(openssl rand -hex 24)
JWT_SECRET=$(openssl rand -hex 32)
JWT_EXPIRE_MINUTES=60
ALLOWED_ORIGINS=__ALLOWED_ORIGINS__
RATE_LIMIT_DEFAULT=100/minute
RATE_LIMIT_AUTH=5/minute
DOCS_ENABLED=true
ZONA_HORARIA_HORAS=-6
S3_BUCKET=__S3_BUCKET__
ENV
  sed -i 's/[[:space:]]*#.*$//' /opt/sfy/.env   # sin comentarios en línea (los lee deploy.sh)
  chown ubuntu:ubuntu /opt/sfy/.env
  chmod 600 /opt/sfy/.env
fi

echo "EC2 B lista: esperando el primer despliegue desde GitHub Actions (rama develop)."
