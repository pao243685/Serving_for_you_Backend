FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Detrás del proxy de la plataforma, --proxy-headers hace que el límite de peticiones use la IP
# real de cada usuario (si no, todos comparten la IP del proxy y el límite de /login se agota).
# La plataforma define $PORT. Un solo worker: sin REDIS_URL el límite vive en memoria de cada proceso.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
