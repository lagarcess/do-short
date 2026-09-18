# do-short

FastAPI URL shortener for DigitalOcean App Platform.

Target region for App Platform (documented only, **not deployed** in this PR): **nyc3**.

## Constraints

- Python 3.12, FastAPI + Pydantic v2, Uvicorn
- SQLite file persistence first (Postgres-ready repository / portable SQL)
- No frontend; API-only
- Env-only config (see `.env.example`)
- In-memory rate limit on `POST /api/v1/links` only
- Soft-delete via `active` flag
- Dockerfile suitable for DigitalOcean App Platform

## API

| Method | Path | Behavior |
|--------|------|----------|
| `POST` | `/api/v1/links` | Create short link (JSON: `url`, optional `alias`). **201** |
| `GET` | `/{code}` | **302** redirect; increments clicks; **404** if missing/inactive |
| `GET` | `/api/v1/links/{code}` | Metadata + clicks |
| `DELETE` | `/api/v1/links/{code}` | Soft-deactivate; **204** or **404** |
| `GET` | `/health` | **200** `{"status":"ok"}` |

Errors are structured JSON: `{"error": "...", "detail": "...", "code": "..."}`.

## Architecture decisions

- **Boundary validation** with Pydantic v2 (`HttpUrl`, alias charset `^[A-Za-z0-9_-]+$`).
- **Repository protocol** (`LinkRepository`) with a SQLite implementation so swapping to Postgres is a connection + dialect tweak, not a rewrite of route handlers.
- **Random codes** via `secrets.token_urlsafe` (truncated); custom aliases validated and uniqueness enforced with **409**.
- **Soft delete**: `active=0`; redirect and metadata treat inactive as **404**.
- **Rate limiting**: process-local sliding window keyed by client IP — fine for a single instance, not for multi-instance production.
- **Config**: `pydantic-settings` from environment / `.env` only.

## What I'd change at 10× traffic

- Move rate limiting to Redis (or edge) so it works across replicas.
- Use Postgres (or managed DB) with connection pooling; App Platform ephemeral disk is a poor fit for SQLite at scale (see below).
- Add idempotency keys / reserved code blocklist / analytics pipeline.
- Structured logging + metrics (Prometheus/OpenTelemetry); background click aggregation if write amplification becomes an issue.
- CDN / edge redirects for hot codes.

## App Platform ephemeral disk note

DigitalOcean App Platform local disk is **ephemeral**: filesystem writes (including SQLite) do **not** survive redeploys, scale events, or instance replacement. For a real App Platform deploy, attach a managed database (Postgres) or an external volume strategy. The Dockerfile defaults `SQLITE_PATH=/tmp/do_short.db` for container convenience; set a durable store for production. Deploy target region: **nyc3**.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
mkdir -p data
uvicorn app.main:app --reload --port 8000
```

Health check:

```bash
curl -s http://localhost:8000/health
```

Create + redirect:

```bash
curl -s -X POST http://localhost:8000/api/v1/links \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com"}'
# then follow Location from:
curl -s -D - -o /dev/null http://localhost:8000/<code>
```

## Test

```bash
pip install -r requirements.txt
pytest -q
```

## Docker

```bash
docker build -t do-short .
docker run --rm -p 8080:8080 -e BASE_URL=http://localhost:8080 do-short
```

## Layout

```
app/
  main.py          # FastAPI routes + middleware
  config.py        # env settings
  models.py        # Pydantic schemas
  db.py            # SQLite connect / schema
  repo.py          # repository interface + SQLite impl
  rate_limit.py    # in-memory limiter
  errors.py        # structured JSON errors
tests/
  test_api.py
Dockerfile
.env.example
requirements.txt
```
