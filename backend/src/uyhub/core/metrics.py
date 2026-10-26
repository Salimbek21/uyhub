"""Prometheus metrics.

Phase 0 exposes the endpoint and the process collectors only. The business metrics
listed in SPEC section 14 are added by the phase that produces them, each declared
next to the code that updates it.
"""

from __future__ import annotations

from prometheus_client import REGISTRY, CollectorRegistry, make_asgi_app
from starlette.types import ASGIApp

registry: CollectorRegistry = REGISTRY
"""The default registry. Process and platform collectors register themselves here."""


def metrics_app() -> ASGIApp:
    """ASGI app rendering the Prometheus exposition format.

    Mounted at ``/metrics`` and reachable only on the internal Docker network
    (SPEC 9.1); Caddy never proxies it.
    """
    app: ASGIApp = make_asgi_app(registry=registry)
    return app
