"""Structured logging.

Logs are JSON, carry ``service``, and are scrubbed of personal data before they are
rendered. CLAUDE.md forbids logging phone numbers, session strings, tokens, API keys
and full post text at INFO or above; ``redact_sensitive`` enforces that mechanically
instead of relying on every call site to remember.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog
from structlog.types import EventDict, Processor, WrappedLogger

REDACTED = "***"
"""Replacement for a value whose key marks it as sensitive."""

MAX_REDACTION_DEPTH = 6
"""How deep to walk nested structures. Bounded so logging cannot blow the stack."""

SENSITIVE_KEYS = frozenset(
    {
        "anthropic_api_key",
        "api_hash",
        "api_key",
        "authorization",
        "backup_passphrase",
        "bot_token",
        "cookie",
        "credentials",
        "init_data",
        "initdata",
        "password",
        "phone",
        "phone_number",
        "phones",
        "phone_hash_key",
        "secret",
        "session",
        "session_string",
        "set-cookie",
        "tg_api_hash",
        "token",
    }
)
"""Keys whose values are replaced wholesale, matched case-insensitively."""

TRUNCATED_KEYS = frozenset({"text", "message_text", "post_text", "description", "raw_text"})
"""Keys holding user-generated post text. Truncated rather than dropped (SPEC 13)."""

TEXT_PREVIEW_CHARS = 120

_PHONE_RE = re.compile(r"\+?998[\s\-().]*\d{2}[\s\-().]*\d{3}[\s\-().]*\d{2}[\s\-().]*\d{2}")
_PHONE_MASK = "+998*********"


def _scrub_text(value: str) -> str:
    """Remove Uzbek phone numbers from a free-text value."""
    return _PHONE_RE.sub(_PHONE_MASK, value)


def _redact_value(key: str, value: Any, depth: int) -> Any:
    lowered = key.lower()
    if lowered in SENSITIVE_KEYS:
        return REDACTED
    if isinstance(value, str):
        scrubbed = _scrub_text(value)
        if lowered in TRUNCATED_KEYS and len(scrubbed) > TEXT_PREVIEW_CHARS:
            return scrubbed[:TEXT_PREVIEW_CHARS] + "…"
        return scrubbed
    if depth < MAX_REDACTION_DEPTH:
        if isinstance(value, MutableMapping):
            return {k: _redact_value(str(k), v, depth + 1) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [_redact_value(key, item, depth + 1) for item in value]
    return value


def redact_sensitive(_logger: WrappedLogger, _method_name: str, event_dict: EventDict) -> EventDict:
    """structlog processor that strips secrets and personal data from every event."""
    return {key: _redact_value(str(key), value, 0) for key, value in event_dict.items()}


def _add_service(service: str) -> Processor:
    """Bind the service name onto every event emitted by this process."""

    def processor(_logger: WrappedLogger, _method_name: str, event_dict: EventDict) -> EventDict:
        event_dict.setdefault("service", service)
        return event_dict

    return processor


def _shared_processors(service: str) -> list[Processor]:
    return [
        structlog.contextvars.merge_contextvars,
        _add_service(service),
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        redact_sensitive,
    ]


def configure_logging(
    service: str,
    *,
    level: str = "INFO",
    log_format: str = "json",
) -> None:
    """Configure structlog and route the standard library's logging through it.

    Safe to call more than once; the last call wins. ``service`` appears on every
    event, including records emitted by third-party libraries.
    """
    shared = _shared_processors(service)

    renderer: Processor
    if log_format == "console":
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
        exception_processor: Processor = structlog.processors.format_exc_info
    else:
        renderer = structlog.processors.JSONRenderer()
        exception_processor = structlog.processors.dict_tracebacks

    structlog.configure(
        processors=[
            *shared,
            exception_processor,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[*shared, exception_processor],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    for existing in root.handlers[:]:
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level.upper())

    # These libraries are chatty at INFO and say nothing we act on.
    for noisy in ("aiobotocore", "botocore", "boto3", "urllib3", "asyncio", "aiohttp"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound logger. Prefer ``get_logger(__name__)``."""
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
