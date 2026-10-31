"""Telegram Mini App authentication (SPEC 9.1).

The Mini App sends `Authorization: tma <initData>`, where ``initData`` is the
percent-encoded query string Telegram handed the web view. Telegram signs it
with a key derived from the bot token, so verifying the signature is what
proves the caller is a real Telegram user opening our Mini App rather than
anyone who guessed a user id.

The algorithm is Telegram's, and is reproduced exactly:

1. split the query string into key/value pairs and drop ``hash``;
2. sort the remaining pairs by key and join them as ``k=v`` with newlines —
   the *data check string*;
3. ``secret = HMAC_SHA256(key=b"WebAppData", msg=bot_token)``;
4. the signature is ``HMAC_SHA256(key=secret, msg=data_check_string)``, hex.

Note the inversion in step 3: the literal ``WebAppData`` is the HMAC *key* and
the bot token is the message, which is the opposite of the login-widget scheme
and the usual place to get this wrong.

Nothing here is logged beyond the Telegram user id. ``initData`` carries a
display name and may carry a photo URL, and the token is a credential.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from urllib.parse import parse_qsl

from uyhub.core.clock import now_utc

SECRET_KEY_SALT = b"WebAppData"
"""Telegram's fixed HMAC key for deriving the per-bot secret."""

MAX_AGE_SECONDS = 24 * 60 * 60
"""SPEC 9.1. An `initData` older than this is refused even if correctly signed:
the web view keeps it for the life of the session, so age is the only thing
limiting how long a leaked one stays useful."""


class InitDataError(Exception):
    """The caller did not present valid, fresh Telegram credentials."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class TelegramUser:
    """The parts of the ``user`` object we store (SPEC 3, ``users``)."""

    tg_user_id: int
    username: str | None
    language_code: str | None
    is_premium: bool


def parse_authorization_header(value: str | None) -> str:
    """Pull the raw ``initData`` out of ``Authorization: tma <initData>``."""
    if not value:
        raise InitDataError("missing_authorization")

    scheme, _, payload = value.partition(" ")
    if scheme.lower() != "tma" or not payload.strip():
        raise InitDataError("unsupported_scheme")
    return payload.strip()


def verify_init_data(init_data: str, *, bot_token: str) -> TelegramUser:
    """Check the signature and freshness, and return who is calling.

    Raises :class:`InitDataError` for every failure, with a reason short enough
    to log and vague enough not to help someone probing the endpoint.
    """
    if not bot_token:
        raise InitDataError("server_has_no_bot_token")

    # `parse_qsl` percent-decodes, which is what the check string is built
    # from. `keep_blank_values` matters: dropping an empty field would change
    # the string we hash and turn a valid signature into an invalid one.
    pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=False)
    if not pairs:
        raise InitDataError("malformed_init_data")

    received_hash = ""
    fields: dict[str, str] = {}
    for key, value in pairs:
        if key == "hash":
            received_hash = value
        else:
            fields[key] = value

    if not received_hash:
        raise InitDataError("missing_hash")

    data_check_string = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret = hmac.new(SECRET_KEY_SALT, bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()

    # Constant time: a byte-by-byte comparison leaks how much of a forged
    # signature was right, which is enough to build one.
    if not hmac.compare_digest(expected, received_hash):
        raise InitDataError("bad_signature")

    _check_age(fields.get("auth_date"))
    return _parse_user(fields.get("user"))


def _check_age(auth_date: str | None) -> None:
    if auth_date is None:
        raise InitDataError("missing_auth_date")
    try:
        issued_at = int(auth_date)
    except ValueError as exc:
        raise InitDataError("malformed_auth_date") from exc

    age = int(now_utc().timestamp()) - issued_at
    if age > MAX_AGE_SECONDS:
        raise InitDataError("expired")
    # A little clock skew is normal; a far-future date is not, and would make
    # `expired` unreachable for as long as the skew lasts.
    if age < -MAX_AGE_SECONDS:
        raise InitDataError("auth_date_in_the_future")


def _parse_user(raw: str | None) -> TelegramUser:
    if not raw:
        raise InitDataError("missing_user")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InitDataError("malformed_user") from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("id"), int):
        raise InitDataError("malformed_user")

    username = payload.get("username")
    language = payload.get("language_code")
    return TelegramUser(
        tg_user_id=payload["id"],
        username=username if isinstance(username, str) else None,
        language_code=language if isinstance(language, str) else None,
        is_premium=payload.get("is_premium") is True,
    )
