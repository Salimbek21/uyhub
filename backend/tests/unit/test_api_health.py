"""Liveness, readiness and metrics behaviour that needs no live dependencies."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest

from uyhub import __version__
from uyhub.api import app as app_module
from uyhub.core.errors import DependencyUnavailableError

pytestmark = pytest.mark.unit


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    """Client without lifespan: these tests must not open real connections."""
    application = app_module.create_app()
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


async def test_healthz_needs_no_dependency(client: httpx.AsyncClient) -> None:
    """A restart loop stays diagnosable only if liveness touches nothing."""
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "api", "version": __version__}


async def test_readyz_reports_ready_when_all_checks_pass(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def ok() -> None:
        return None

    for name in app_module.READINESS_CHECKS:
        monkeypatch.setitem(app_module.READINESS_CHECKS, name, ok)

    response = await client.get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"] == {"postgres": "ok", "redis": "ok", "s3": "ok"}


async def test_readyz_returns_503_when_a_dependency_is_down(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def ok() -> None:
        return None

    async def down() -> None:
        raise DependencyUnavailableError("redis", "ConnectionError")

    monkeypatch.setitem(app_module.READINESS_CHECKS, "postgres", ok)
    monkeypatch.setitem(app_module.READINESS_CHECKS, "redis", down)
    monkeypatch.setitem(app_module.READINESS_CHECKS, "s3", ok)

    response = await client.get("/readyz")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"] == {"postgres": "ok", "redis": "ConnectionError", "s3": "ok"}


async def test_readyz_does_not_leak_connection_details(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reason is an exception class name, never a DSN with a password."""

    async def down() -> None:
        raise DependencyUnavailableError("postgres", "OperationalError") from ValueError(
            "postgresql+asyncpg://uyhub:secret@host/db"
        )

    monkeypatch.setitem(app_module.READINESS_CHECKS, "postgres", down)
    response = await client.get("/readyz")
    assert "secret" not in response.text


async def test_readyz_survives_an_unexpected_exception(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A probe raising something unforeseen must still produce a 503, not a 500."""

    async def boom() -> None:
        raise RuntimeError("unexpected")

    monkeypatch.setitem(app_module.READINESS_CHECKS, "s3", boom)
    response = await client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["checks"]["s3"] == "error"


async def test_metrics_endpoint_is_mounted(client: httpx.AsyncClient) -> None:
    response = await client.get("/metrics/")
    assert response.status_code == 200
    assert "python_info" in response.text
