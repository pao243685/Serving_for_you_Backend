#!/usr/bin/env bash
# Lo ejecuta GitHub Actions por SSH:  bash /opt/sfy/deploy.sh <tag-de-la-imagen> [usuario-docker-hub]
# Descarga la imagen nueva, reinicia el backend y, si no responde, vuelve a la versión anterior.
set -euo pipefail
cd /opt/sfy

NEW_TAG="${1:?Uso: deploy.sh <tag> [usuario-docker-hub]}"
HUB_USER="${2:-}"

set_env() {   # set_env CLAVE VALOR  -> actualiza o agrega la línea en .env
  touch .env
  if grep -q "^$1=" .env; then sed -i "s|^$1=.*|$1=$2|" .env; else echo "$1=$2" >> .env; fi
}
get_env() { grep -E "^$1=" .env | head -n1 | cut -d= -f2- || true; }

# El usuario de Docker Hub lo manda el pipeline (variable DOCKERHUB_USERNAME de GitHub)
if [ -n "$HUB_USER" ]; then set_env DOCKERHUB_USER "$HUB_USER"; fi

PREV_TAG="$(get_env BACKEND_TAG)"; PREV_TAG="${PREV_TAG:-latest}"
REPO="$(get_env DOCKERHUB_USER)/sfy-backend"

echo ">> Desplegando $REPO:$NEW_TAG (anterior: $PREV_TAG)"
set_env BACKEND_TAG "$NEW_TAG"
docker compose pull backend
docker compose up -d --remove-orphans

for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
    echo ">> OK: el backend responde"
    # Conserva solo la versión nueva, la anterior (por si hay que volver) y latest
    docker images --format '{{.Repository}}:{{.Tag}}' "$REPO" \
      | grep -v -e ":$NEW_TAG$" -e ":$PREV_TAG$" -e ":latest$" | xargs -r docker rmi || true
    docker image prune -f >/dev/null
    exit 0
  fi
  sleep 2
done

echo "!! El backend no respondió. Volviendo a $PREV_TAG" >&2
docker compose logs --tail=40 backend >&2 || true
set_env BACKEND_TAG "$PREV_TAG"
docker compose up -d backend || true
exit 1
