"""Telethon client construction.

The session file is created by a human running ``make login-userbot`` and is the
only thing standing between this process and a logged-in Telegram account, so it
is kept at mode 0600 in a Docker volume and never leaves the server (SPEC 4.1).
"""

from __future__ import annotations

import stat
from pathlib import Path
from typing import TYPE_CHECKING

from uyhub.core.config import Settings, get_settings
from uyhub.core.errors import ConfigError
from uyhub.core.logging import get_logger

if TYPE_CHECKING:
    from telethon import TelegramClient

log = get_logger(__name__)

DEVICE_MODEL = "UyHub Collector"
SYSTEM_VERSION = "Linux"
CONNECTION_RETRIES = 5
REQUEST_RETRIES = 5
TIMEOUT_SECONDS = 30


def build_client(settings: Settings | None = None) -> TelegramClient:
    """Create a client bound to the configured session file.

    Does not connect and never prompts: a missing session is an operator error,
    not something a service process should try to fix by asking for a code.
    """
    from telethon import TelegramClient

    cfg = settings or get_settings()
    if not cfg.has_telegram_credentials:
        msg = "TG_API_ID and TG_API_HASH must be set to run the collector"
        raise ConfigError(msg)

    # Telethon opens the session with sqlite, which fails with an opaque
    # "unable to open database file" if the directory is missing — and the
    # directory is missing on any machine that is not the Docker image, whose
    # Dockerfile creates /data/sessions for it.
    session_path = cfg.tg_session_path.expanduser()
    session_path.parent.mkdir(parents=True, exist_ok=True)
    _check_session_permissions(session_path)

    return TelegramClient(
        str(session_path),
        cfg.tg_api_id,
        cfg.tg_api_hash.get_secret_value(),
        device_model=DEVICE_MODEL,
        system_version=SYSTEM_VERSION,
        connection_retries=CONNECTION_RETRIES,
        request_retries=REQUEST_RETRIES,
        timeout=TIMEOUT_SECONDS,
        auto_reconnect=True,
    )


def _check_session_permissions(path: Path) -> None:
    """Warn loudly if the session file is readable by anyone else.

    A readable session file is a full account takeover, so this is worth a log
    line every startup rather than a one-off note in the runbook.
    """
    if not path.exists():
        log.warning("collector.session_missing", path=str(path))
        return

    mode = path.stat().st_mode
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        log.warning("collector.session_permissions_loose", path=str(path), mode=oct(mode & 0o777))
