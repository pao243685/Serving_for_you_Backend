#!/usr/bin/env bash
# Prepara una EC2 con Ubuntu Server 24.04: instala Docker y crea /opt/sfy.
# Uso (en CADA instancia, una sola vez):   sudo bash setup-ec2.sh front   |   sudo bash setup-ec2.sh back
# Es repetible: puedes volver a ejecutarlo sin problema.
set -euo pipefail

ROL="${1:-}"
if [[ "$ROL" != "front" && "$ROL" != "back" ]]; then
  echo "Uso: sudo bash setup-ec2.sh front|back" >&2; exit 1
fi
if [[ $EUID -ne 0 ]]; then echo "Ejecuta con sudo" >&2; exit 1; fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y ca-certificates curl gnupg unzip

# --- Docker Engine + Compose (repositorio oficial) ---
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
# shellcheck disable=SC1091  # /etc/os-release solo existe en la EC2 (Ubuntu)
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Docker arranca solo con la instancia (así basta con iniciar el laboratorio)
systemctl enable --now docker
usermod -aG docker ubuntu

# Rotación de logs de Docker (evita llenar el disco)
cat > /etc/docker/daemon.json <<'JSON'
{ "log-driver": "json-file", "log-opts": { "max-size": "10m", "max-file": "3" } }
JSON
systemctl restart docker

# Carpeta de trabajo
mkdir -p /opt/sfy
chown ubuntu:ubuntu /opt/sfy

if [[ "$ROL" == "front" ]]; then
  # El puerto 22 está abierto a Internet (los runners de GitHub tienen IP variable):
  # fail2ban bloquea a quien intente adivinar acceso.
  apt-get install -y fail2ban
  systemctl enable --now fail2ban
fi

if [[ "$ROL" == "back" ]]; then
  # AWS CLI para respaldos a S3 (usa el rol LabInstanceProfile de la instancia, sin claves)
  snap install aws-cli --classic
  # Respaldo de la BD a S3 cada hora (si S3_BUCKET está vacío en .env, no hace nada)
  cat > /etc/cron.d/sfy-backup <<'CRON'
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/snap/bin
15 * * * * ubuntu bash /opt/sfy/backup.sh >> /var/log/sfy-backup.log 2>&1
CRON
  chmod 644 /etc/cron.d/sfy-backup
  touch /var/log/sfy-backup.log && chown ubuntu:ubuntu /var/log/sfy-backup.log
fi

echo
echo "Listo ($ROL). Cierra la sesión SSH y vuelve a entrar para que el grupo 'docker' surta efecto."
echo "Siguiente paso: crear /opt/sfy/.env (plantilla en deploy/env.example del repo)."
