"""FastAPI application: URL shortener API."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import Settings, get_settings
from app.db import connect, init_db
from app.errors import (
    AppError,
    app_error_handler,
    http_exception_handler,
    validation_exception_handler,
)
from app.models import (
    CreateLinkRequest,
    HealthResponse,
    LinkCreatedResponse,
    LinkMetadataResponse,
)
from app.rate_limit import InMemoryRateLimiter
from app.repo import LinkRecord, SqliteLinkRepository

logger = logging.getLogger("do_short")


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format='{"level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
        force=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    _configure_logging(settings.log_level)
    conn = connect(settings.sqlite_path)
    init_db(conn)
    app.state.settings = settings
    app.state.db = conn
    app.state.repo = SqliteLinkRepository(conn)
    app.state.rate_limiter = InMemoryRateLimiter(
        settings.rate_limit_requests,
        settings.rate_limit_window_seconds,
    )
    logger.info("startup sqlite_path=%s base_url=%s", settings.sqlite_path, settings.base_url)
    yield
    conn.close()
    logger.info("shutdown")


app = FastAPI(
    title="do-short",
    description="FastAPI URL shortener",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)


def get_repo(request: Request) -> SqliteLinkRepository:
    return request.app.state.repo


def get_limiter(request: Request) -> InMemoryRateLimiter:
    return request.app.state.rate_limiter


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _short_url(settings: Settings, code: str) -> str:
    return f"{settings.base_url.rstrip('/')}/{code}"


def _to_created(settings: Settings, record: LinkRecord) -> LinkCreatedResponse:
    return LinkCreatedResponse(
        code=record.code,
        url=record.url,
        short_url=_short_url(settings, record.code),
        created_at=record.created_at,
        clicks=record.clicks,
        active=record.active,
    )


def _to_meta(settings: Settings, record: LinkRecord) -> LinkMetadataResponse:
    return LinkMetadataResponse(
        code=record.code,
        url=record.url,
        short_url=_short_url(settings, record.code),
        created_at=record.created_at,
        clicks=record.clicks,
        active=record.active,
    )


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    response = await call_next(request)
    logger.info(
        "method=%s path=%s status=%s client=%s",
        request.method,
        request.url.path,
        response.status_code,
        _client_key(request),
    )
    return response


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post("/api/v1/links", response_model=LinkCreatedResponse, status_code=201)
def create_link(
    body: CreateLinkRequest,
    request: Request,
    repo: Annotated[SqliteLinkRepository, Depends(get_repo)],
    limiter: Annotated[InMemoryRateLimiter, Depends(get_limiter)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> LinkCreatedResponse:
    key = _client_key(request)
    if not limiter.allow(key):
        raise AppError(
            429,
            "Rate limit exceeded",
            detail=f"Max {settings.rate_limit_requests} creates per "
            f"{settings.rate_limit_window_seconds}s",
            code="rate_limited",
        )

    record = repo.create(url=str(body.url), code=body.alias)
    logger.info("created code=%s", record.code)
    return _to_created(settings, record)


@app.get("/api/v1/links/{code}", response_model=LinkMetadataResponse)
def get_link(
    code: str,
    repo: Annotated[SqliteLinkRepository, Depends(get_repo)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> LinkMetadataResponse:
    record = repo.get(code)
    if record is None or not record.active:
        raise AppError(404, "Link not found", code="not_found")
    return _to_meta(settings, record)


@app.delete("/api/v1/links/{code}", status_code=204)
def delete_link(
    code: str,
    repo: Annotated[SqliteLinkRepository, Depends(get_repo)],
) -> Response:
    if not repo.soft_delete(code):
        raise AppError(404, "Link not found", code="not_found")
    return Response(status_code=204)


@app.get("/{code}")
def redirect_link(
    code: str,
    repo: Annotated[SqliteLinkRepository, Depends(get_repo)],
) -> RedirectResponse:
    # Reserve API and health paths from being treated as codes
    if code in ("api", "health", "docs", "openapi.json", "redoc"):
        raise AppError(404, "Link not found", code="not_found")

    record = repo.increment_clicks(code)
    if record is None:
        raise AppError(404, "Link not found", code="not_found")
    return RedirectResponse(url=record.url, status_code=302)
