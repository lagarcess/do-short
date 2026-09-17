"""API tests for do-short."""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import connect, init_db
from app.main import app
from app.rate_limit import InMemoryRateLimiter
from app.repo import SqliteLinkRepository


def test_health(client: TestClient):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_create_and_redirect(client: TestClient):
    r = client.post("/api/v1/links", json={"url": "https://example.com/path"})
    assert r.status_code == 201
    body = r.json()
    assert "code" in body
    assert body["url"] == "https://example.com/path"
    assert body["short_url"] == f"http://testserver/{body['code']}"
    assert body["clicks"] == 0
    assert body["active"] is True

    code = body["code"]
    redir = client.get(f"/{code}", follow_redirects=False)
    assert redir.status_code == 302
    assert redir.headers["location"] == "https://example.com/path"

    meta = client.get(f"/api/v1/links/{code}")
    assert meta.status_code == 200
    assert meta.json()["clicks"] == 1


def test_custom_alias(client: TestClient):
    r = client.post(
        "/api/v1/links",
        json={"url": "https://example.com", "alias": "my-link"},
    )
    assert r.status_code == 201
    assert r.json()["code"] == "my-link"

    conflict = client.post(
        "/api/v1/links",
        json={"url": "https://example.com/other", "alias": "my-link"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "alias_taken"


def test_invalid_alias_charset(client: TestClient):
    r = client.post(
        "/api/v1/links",
        json={"url": "https://example.com", "alias": "bad alias!"},
    )
    assert r.status_code == 422
    assert r.json()["code"] == "validation_error"


def test_invalid_url(client: TestClient):
    r = client.post("/api/v1/links", json={"url": "not-a-url"})
    assert r.status_code == 422


def test_get_missing(client: TestClient):
    r = client.get("/api/v1/links/does-not-exist")
    assert r.status_code == 404
    assert r.json()["code"] == "not_found"


def test_redirect_missing(client: TestClient):
    r = client.get("/nope", follow_redirects=False)
    assert r.status_code == 404


def test_soft_delete(client: TestClient):
    created = client.post(
        "/api/v1/links",
        json={"url": "https://example.com/del", "alias": "todelete"},
    )
    assert created.status_code == 201

    deleted = client.delete("/api/v1/links/todelete")
    assert deleted.status_code == 204

    meta = client.get("/api/v1/links/todelete")
    assert meta.status_code == 404

    redir = client.get("/todelete", follow_redirects=False)
    assert redir.status_code == 404

    again = client.delete("/api/v1/links/todelete")
    assert again.status_code == 404


def test_persistence_across_connections(tmp_path, monkeypatch):
    """Create a link, close connection, reopen — record still resolves."""
    db_path = tmp_path / "persist.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))
    monkeypatch.setenv("BASE_URL", "http://testserver")
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "100")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "60")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    get_settings.cache_clear()

    with TestClient(app) as c1:
        r = c1.post(
            "/api/v1/links",
            json={"url": "https://example.com/persist", "alias": "persist1"},
        )
        assert r.status_code == 201

    # New connection outside the app lifespan
    conn = connect(str(db_path))
    init_db(conn)
    repo = SqliteLinkRepository(conn)
    record = repo.get("persist1", active_only=True)
    conn.close()
    assert record is not None
    assert record.url == "https://example.com/persist"

    get_settings.cache_clear()
    with TestClient(app) as c2:
        redir = c2.get("/persist1", follow_redirects=False)
        assert redir.status_code == 302
        assert redir.headers["location"] == "https://example.com/persist"

    get_settings.cache_clear()


def test_rate_limit(tmp_path, monkeypatch):
    db_path = tmp_path / "rl.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))
    monkeypatch.setenv("BASE_URL", "http://testserver")
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "3")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "60")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    get_settings.cache_clear()

    with TestClient(app) as c:
        for i in range(3):
            r = c.post("/api/v1/links", json={"url": f"https://example.com/{i}"})
            assert r.status_code == 201, i
        blocked = c.post("/api/v1/links", json={"url": "https://example.com/x"})
        assert blocked.status_code == 429
        assert blocked.json()["code"] == "rate_limited"

    get_settings.cache_clear()


def test_rate_limiter_unit():
    lim = InMemoryRateLimiter(max_requests=2, window_seconds=60)
    assert lim.allow("a") is True
    assert lim.allow("a") is True
    assert lim.allow("a") is False
    assert lim.allow("b") is True
    lim.reset()
    assert lim.allow("a") is True
