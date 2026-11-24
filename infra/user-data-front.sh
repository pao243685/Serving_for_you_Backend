#!/bin/bash
# user-data de la EC2 A (Caddy + frontend). Corre como root UNA vez, al crear la instancia.
# crear-infra.sh reemplaza __BACKEND_UPSTREAM__, __SITE_ADDRESS__, __API_ADDRESS__ y __SETUP_B64__.
#
# Mientras no exista el pipeline del frontend, levanta un Caddy PROVISIONAL (imagen oficial)
# con la misma configuración que el del front: HTTPS automático, /api/* -> backend y una
# página de espera. Cuando el pipeline del front despliegue, reemplaza docker-compose.yml
# (mismo proyecto "sfy-front" y servicio "web", así que conserva los certificados).
set -euxo pipefail
exec > >(tee -a /var/log/sfy-user-data.log) 2>&1

# deploy/setup-ec2.sh incrustado por crear-infra.sh (base64)
echo "__SETUP_B64__" | base64 -d > /root/setup-ec2.sh
bash /root/setup-ec2.sh front

cd /opt/sfy
if [ ! -f .env ]; then
  cat > .env <<'ENV'
DOCKERHUB_USER=pendiente
FRONTEND_TAG=latest
BACKEND_UPSTREAM=__BACKEND_UPSTREAM__
SITE_ADDRESS=__SITE_ADDRESS__
API_ADDRESS=__API_ADDRESS__
ENV
  chmod 600 .env
fi

mkdir -p bootstrap/site
cat > bootstrap/Caddyfile <<'CADDY'
{
	admin off
}

:8081 {
	respond /healthz "ok" 200
}

{$SITE_ADDRESS::80} {
	encode zstd gzip

	# /api/loquesea -> http://BACKEND_UPSTREAM/loquesea (se quita el prefijo /api)
	handle_path /api/* {
		reverse_proxy {$BACKEND_UPSTREAM}
	}

	handle {
		root * /srv
		try_files {path} /index.html
		file_server
	}

	header {
		X-Content-Type-Options nosniff
		X-Frame-Options DENY
		Referrer-Policy strict-origin-when-cross-origin
		-Server
	}
}

# Dominio propio de la API (ej. serving-for-u-back.duckdns.org): todo va al backend.
# Si llega con /api (Swagger usa root_path=/api) se quita el prefijo.
# Sin API_ADDRESS escucha en :8082, que no está publicado (queda inactivo).
{$API_ADDRESS::8082} {
	encode zstd gzip
	handle_path /api/* {
		reverse_proxy {$BACKEND_UPSTREAM}
	}
	handle {
		reverse_proxy {$BACKEND_UPSTREAM}
	}
	header {
		X-Content-Type-Options nosniff
		Referrer-Policy strict-origin-when-cross-origin
		-Server
	}
}
CADDY

cat > bootstrap/site/index.html <<'HTML'
<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Serving for you</title>
<style>body{font-family:system-ui,sans-serif;max-width:40rem;margin:4rem auto;padding:0 1rem;color:#2c2c2a}
code{background:#f1efe8;padding:.1rem .3rem;border-radius:4px}</style></head>
<body><h1>Serving for you</h1>
<p>La infraestructura está arriba. El frontend todavía no se ha desplegado.</p>
<p>API: <a href="/api/health"><code>/api/health</code></a> · Documentación: <a href="/api/docs"><code>/api/docs</code></a></p>
<p>Dominio de la API: <a href="https://serving-for-u-back.duckdns.org/docs"><code>serving-for-u-back.duckdns.org</code></a></p>
</body></html>
HTML

cat > docker-compose.yml <<'YML'
# PROVISIONAL: lo reemplaza el pipeline del frontend (deploy/docker-compose.prod.yml del repo del front)
name: sfy-front

services:
  web:
    image: caddy:2-alpine
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    environment:
      SITE_ADDRESS: ${SITE_ADDRESS:-:80}
      BACKEND_UPSTREAM: ${BACKEND_UPSTREAM:?Define BACKEND_UPSTREAM en /opt/sfy/.env}
      API_ADDRESS: ${API_ADDRESS:-}
    volumes:
      - ./bootstrap/Caddyfile:/etc/caddy/Caddyfile:ro
      - ./bootstrap/site:/srv:ro
      - caddy_data:/data
      - caddy_config:/config
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://127.0.0.1:8081/healthz"]
      interval: 15s
      timeout: 3s
      retries: 3
      start_period: 10s

volumes:
  caddy_data:
  caddy_config:
YML

chown -R ubuntu:ubuntu /opt/sfy
docker compose up -d
echo "EC2 A lista."
