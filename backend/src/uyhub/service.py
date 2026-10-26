"""Shared service lifecycle.

Every long-running entrypoint (collector, parser, bot, poster, scheduler) must shut
down cleanly on SIGTERM so Docker restarts and deploys do not drop in-flight work
(SPEC section 4.4). The contract lives here from Phase 0 so later phases inherit it
rather than bolt it on.
"""

from __future__ import annotations

import asyncio
import signal

from uyhub.core.logging import get_logger

log = get_logger(__name__)

SHUTDOWN_GRACE_SECONDS = 20.0
"""Upper bound on finishing in-flight work after SIGTERM (SPEC 4.4)."""


def install_signal_handlers(stop: asyncio.Event) -> None:
    """Set ``stop`` when the process receives SIGTERM or SIGINT."""
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # pragma: no cover - Windows only
            signal.signal(sig, lambda *_: stop.set())


async def run_until_stopped(service: str) -> None:
    """Placeholder main loop: start, idle, shut down cleanly.

    Phase 0 has no work for these services yet. Each phase replaces this with the
    real loop while keeping the same startup and shutdown logging.
    """
    stop = asyncio.Event()
    install_signal_handlers(stop)
    log.info("service.started", service=service)
    try:
        await stop.wait()
    finally:
        log.info("service.stopped", service=service)
