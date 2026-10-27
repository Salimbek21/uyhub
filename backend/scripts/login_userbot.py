#!/usr/bin/env python
"""Interactive Telethon login. Run by a human, in their own terminal.

This script is the only place in the project that asks for a phone number, a
login code or a 2FA password. None of the three is logged, echoed into a file,
or sent anywhere except Telegram — and nobody should ever be asked to paste one
into a chat window (CLAUDE.md "Hard safety rules").

    make login-userbot

What it does:
  1. asks for the phone number of the dedicated userbot SIM
  2. sends a login code and asks for it (and the 2FA password, if set)
  3. writes the session file at TG_SESSION_PATH with mode 0600
  4. registers the account in `tg_accounts`, storing only the last four digits

Running it again for the same label re-uses the session if it is still valid.
"""

from __future__ import annotations

import asyncio
import getpass
import os
import stat
import sys
from pathlib import Path

# The script lives next to the package but is not part of it.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from uyhub.collector.accounts import ensure_account
from uyhub.core.config import get_settings
from uyhub.core.db import dispose_engine, session_scope

DEFAULT_LABEL = "primary"


def _prompt(label: str) -> str:
    value = input(f"{label}: ").strip()
    if not value:
        print(f"{label} is required")  # noqa: T201 - this script is an interactive tool
        raise SystemExit(1)
    return value


async def main() -> int:
    from telethon import TelegramClient
    from telethon.errors import SessionPasswordNeededError

    settings = get_settings()
    if not settings.has_telegram_credentials:
        print("TG_API_ID and TG_API_HASH must be set in .env first")  # noqa: T201
        return 1

    session_path = settings.tg_session_path
    session_path.parent.mkdir(parents=True, exist_ok=True)

    label = os.environ.get("TG_ACCOUNT_LABEL", DEFAULT_LABEL)
    print(f"Session file : {session_path}")  # noqa: T201
    print(f"Account label: {label}")  # noqa: T201
    print()  # noqa: T201

    phone = _prompt("Userbot phone number (with country code, e.g. +998901234567)")

    client = TelegramClient(
        str(session_path),
        settings.tg_api_id,
        settings.tg_api_hash.get_secret_value(),
        device_model="UyHub Collector",
        system_version="Linux",
    )

    await client.connect()
    try:
        if await client.is_user_authorized():
            print("Already authorised; the existing session is still valid.")  # noqa: T201
        else:
            await client.send_code_request(phone)
            code = _prompt("Login code Telegram just sent")
            try:
                await client.sign_in(phone=phone, code=code)
            except SessionPasswordNeededError:
                password = getpass.getpass("Two-factor password (not echoed): ")
                await client.sign_in(password=password)

        me = await client.get_me()
        print(f"Signed in as user id {me.id}")  # noqa: T201
    finally:
        await client.disconnect()

    _harden(session_path)

    async with session_scope() as session:
        account = await ensure_account(session, label=label, phone=phone)
        account_id = account.id
    await dispose_engine()

    print()  # noqa: T201
    print(f"Account {account_id} ({label}) is active.")  # noqa: T201
    print("Next: uyhub sources add <@username or t.me link> --priority 1")  # noqa: T201
    return 0


def _harden(path: Path) -> None:
    """Make the session file readable by its owner only."""
    if path.exists():
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        print(f"Session file permissions set to 0600: {path}")  # noqa: T201


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
