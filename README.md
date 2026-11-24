# Serving for you · Backend

API de **FastAPI + PostgreSQL** de la plataforma *Serving for you*. Este repo incluye
todo lo necesario para desplegarlo en **AWS EC2** con **GitHub Actions + Docker Hub**,
tal como lo plantea la guía de despliegue.

```
.
├── .github/workflows/ci-cd.yml   # CI + CD (lint, seguridad, BD, imagen, deploy SSH)
├── app/                          # código FastAPI (api, core, models, schemas, services)
├── db/
│   ├── 01_schema.sql … 04_permisos_rls.sql   # esquema v3 (roles, funciones, RLS)
│   ├── tests/smoke.sql          # pruebas de la BD (las corre el CI)
│   └── squema-1.0.0.sql         # esquema anterior, sólo como referencia
├── deploy/
│   ├── docker-compose.prod.yml  # se copia a /opt/sfy/docker-compose.yml en la EC2
│   ├── deploy.sh                # deploy con reversión automática (lo llama el CI)
│   ├── backup.sh                # respaldo de la BD a S3 (cron horario)
│   ├── setup-ec2.sh             # prepara la EC2 (Docker, cron, AWS CLI) — una vez
│   ├── init-db/99_set_backend_password.sh
│   └── env.example              # plantilla de /opt/sfy/.env
├── infra/                       # crear-infra.sh (AWS CLI) + user-data de cada EC2
├── Dockerfile · .dockerignore
├── ruff.toml                    # política de lint (la misma que corre el CI)
└── requirements.txt
```

## Correr en local

```bash
python -m venv .venv && . .venv/Scripts/activate     # en Windows
pip install -r requirements.txt
cp .env.example .env                                 # llena DATABASE_URL y JWT_SECRET
uvicorn app.main:app --reload
# Health check:  http://127.0.0.1:8000/health  ->  {"status":"ok"}
```

## Validaciones del CI (pull requests, `develop` y `main`)

| Paso | Herramienta |
|---|---|
| Lint | `ruff check app` (configurado en `ruff.toml`) |
| Seguridad del código | `bandit -q -r app -ll` |
| Dependencias vulnerables | `pip-audit -r requirements.txt` |
| Secretos en el repo/historial | `gitleaks detect` |
| Esquema + pruebas de la BD | `psql` sobre Postgres 16: `db/01…04.sql` + `db/tests/smoke.sql` |
| Pruebas unitarias | `pytest` (código de salida 5 = sin pruebas, se permite) |
| Imagen Docker | `docker build` + `trivy` (vulnerabilidades CRITICAL) |
| Publicar | Docker Hub (`$DOCKERHUB_USER/sfy-backend:<sha>` y `:<rama>`) — en `develop` y `main` |
| Desplegar | SSH con salto por la EC2 del front → EC2 B — automático en `develop`, con aprobación en `main` |

Comandos para correr las mismas validaciones a mano:

```bash
ruff check app
bandit -q -r app -ll
pip-audit -r requirements.txt
pytest -q                       # 5 = sin pruebas todavía
docker build -t sfy-backend:ci .
```

## Despliegue en AWS

Arquitectura: **GitHub Actions → Docker Hub → EC2 A (Caddy + frontend, pública) →
EC2 B (backend + Postgres, sólo red privada)**. La EC2 B **no acepta nada de Internet**:
el deploy entra con `ProxyJump` por la EC2 A. Los dos dominios (DuckDNS) apuntan a la
IP elástica de la EC2 A y Caddy decide por nombre:

| Dominio | Qué sirve |
|---|---|
| `https://serving-for-u.duckdns.org` | el frontend; `/api/*` → backend (sin el prefijo) |
| `https://serving-for-u-back.duckdns.org` | la API directo (`/docs`, `/health`, endpoints) |

Así la EC2 B nunca queda expuesta: la API tiene su propio dominio pero entra por el mismo Caddy.

| Rama | Qué pasa en cada push |
|---|---|
| `develop` | CI → imagen `sfy-backend:<sha>` y `:develop` en Docker Hub → **despliegue automático** en la EC2 B (environment `develop`) |
| `main` | CI → imagen `:<sha>`, `:main` y `:latest` → despliegue **con aprobación** (environment `production`) |
| Pull request | Solo CI |

Si `/health` no responde tras desplegar, `deploy.sh` vuelve a la versión anterior y el job falla.

### 1. Crear la infraestructura (una vez)

En la terminal del **AWS Academy Learner Lab** (ya trae credenciales):

```bash
curl -fsSL https://raw.githubusercontent.com/pao243685/Serving_for_you_Backend/develop/infra/crear-infra.sh | bash
```

Crea los grupos `sfy-front-sg` y `sfy-back-sg`, la IP elástica, el bucket privado de respaldos y las dos EC2
(Ubuntu 24.04, `t3.small`, `LabInstanceProfile`, llave `vockey`). Cada EC2 se configura sola
con su *user-data* (`infra/user-data-*.sh`): Docker, `/opt/sfy/.env` con contraseñas generadas
**en la propia instancia**, cron de respaldos a S3 (B) y `fail2ban` (A). Al final imprime
los valores para GitHub. Mientras no exista el pipeline del frontend, la EC2 A corre un
Caddy provisional con el mismo `Caddyfile` (HTTPS + `/api` → backend).

### 2. Secretos y variables de GitHub (Settings → Secrets and variables → Actions)

| Nombre | Tipo | Valor |
|---|---|---|
| `DOCKERHUB_USERNAME` | **Variable** (o secreto) | tu usuario de Docker Hub |
| `DOCKERHUB_TOKEN` | Secreto | token de Docker Hub con permisos *Read, Write, Delete* |
| `EC2_SSH_KEY` | Secreto | `labsuser.pem` completo (Learner Lab → AWS Details → Download PEM) |
| `EC2_FRONT_HOST` | Secreto | IP elástica de la EC2 A (la imprime `crear-infra.sh`) |
| `EC2_BACK_PRIVATE_IP` | Secreto | IP privada de la EC2 B (la imprime `crear-infra.sh`) |

### 3. Desplegar

Haz push a `develop` (o *Actions → CI/CD backend → Run workflow* sobre `develop`).
Verifica: `https://serving-for-u-back.duckdns.org/health` → `{"status":"ok"}`,
la documentación en `https://serving-for-u-back.duckdns.org/docs` y el sitio en
`https://serving-for-u.duckdns.org`.

### Dominios (DuckDNS)

En [duckdns.org](https://www.duckdns.org) los subdominios `serving-for-u` y
`serving-for-u-back` apuntan a la IP elástica de la EC2 A. La IP elástica no cambia al
reiniciar el lab, así que no hace falta actualizarlos. Si se crea otra IP elástica,
actualiza ambos en DuckDNS y `SITE_ADDRESS`/`API_ADDRESS` (EC2 A) y `ALLOWED_ORIGINS` (EC2 B).

### Base de datos

El servidor crea la BD la primera vez (volumen vacío) con `deploy/init-db/`:
`01_schema.sh` aplica **`db/squema-1.0.0.sql`** (el esquema que usa el código hoy) y
`99_set_backend_password.sh` crea `app_backend` con permisos de lectura/escritura (sin
ser dueño de las tablas). El esquema **v3** (`db/01…04_*.sql`, roles + RLS) se sigue
probando en el CI y queda listo para cuando el backend use `SET LOCAL ROLE`.

## Operación

```bash
cd /opt/sfy
docker compose ps                      # estado (db debe estar "healthy")
docker compose logs -f --tail=100 backend
/opt/sfy/backup.sh                     # respaldo manual a S3
```

Después de cada sesión del lab basta con **Start Lab**: Docker y los contenedores
arrancan solos (`restart: unless-stopped`), la BD conserva sus datos y la IP elástica no cambia.
