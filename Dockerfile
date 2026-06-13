# Dockerfile za jn-watchdog Flask app
# Production image: gunicorn, non-root user, slim base.

FROM python:3.13-slim

# Sistemske nastavitve: brez .pyc datotek, unbuffered izpis za loge
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Europe/Ljubljana

# tzdata — da urnik (07:00) teče po slovenskem času, ne UTC
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Najprej samo requirements — boljši layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Aplikacijska koda
COPY . .

# Non-root uporabnik; /data je volume za SQLite bazo
RUN groupadd --system app && useradd --system --gid app --no-create-home app \
    && mkdir -p /data \
    && chown -R app:app /app /data

USER app

# Baza živi na volume /data (glej docker-compose.yml)
ENV DB_PATH=/data/narocila.db \
    PORT=5000

EXPOSE 5000

# Healthcheck na obstoječi /zdravje endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/zdravje', timeout=4).status == 200 else 1)"

# Gunicorn: 2 workerja zadostujeta za začetek (CX22 ima 2 vCPU)
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "60", "--access-logfile", "-", "server:app"]
