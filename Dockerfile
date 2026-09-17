# DigitalOcean App Platform — Python 3.12
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SQLITE_PATH=/tmp/do_short.db \
    BASE_URL=http://localhost:8000 \
    RATE_LIMIT_REQUESTS=30 \
    RATE_LIMIT_WINDOW_SECONDS=60 \
    LOG_LEVEL=INFO

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# App Platform listens on $PORT; default 8080 for local docker runs
EXPOSE 8080
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
