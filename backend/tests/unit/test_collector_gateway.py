"""Translating Telethon objects into our own shapes (SPEC 4.3, 4.5).

Albums are the interesting case: Telegram sends one message per photo, the
caption sits on exactly one of them, and SPEC section 3 wants the whole thing as
a single ``raw_messages`` row keyed by the first message id.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest

from uyhub.collector.accounts import mask_phone
from uyhub.collector.gateway import (
    _fold_consecutive_albums,
    _invite_hash,
    _media_of,
    _to_incoming,
    fold_album,
)
from uyhub.core.clock import now_utc

pytestmark = pytest.mark.unit


class StubMessage:
    """The handful of Telethon ``Message`` attributes the gateway reads."""

    def __init__(
        self,
        *,
        message_id: int,
        chat_id: int = -100123,
        text: str = "",
        grouped_id: int | None = None,
        photo: object | None = None,
        video: object | None = None,
        document: object | None = None,
        size: int | None = None,
        out: bool = False,
        date: datetime | None = None,
        edit_date: datetime | None = None,
    ) -> None:
        self.id = message_id
        self.chat_id = chat_id
        self.text = text
        self.grouped_id = grouped_id
        self.photo = photo
        self.video = video
        self.document = document
        self.out = out
        self.date = date or now_utc()
        self.edit_date = edit_date
        self.media = photo or video or document
        self.file = _StubFile(size) if size is not None else None


class _StubFile:
    def __init__(self, size: int) -> None:
        self.size = size
        self.width = 1280
        self.height = 960


def _photo_message(message_id: int, **kwargs: Any) -> StubMessage:
    return StubMessage(message_id=message_id, photo=object(), size=2048, **kwargs)


def test_message_without_media_has_none() -> None:
    assert _media_of(StubMessage(message_id=1, text="hello")) == []


def test_photo_is_described_without_downloading() -> None:
    (media,) = _media_of(_photo_message(7))
    assert media.kind == "photo"
    assert media.is_photo
    assert media.message_id == 7
    assert media.size_bytes == 2048
    assert media.width == 1280


def test_video_is_recorded_but_not_a_photo() -> None:
    (media,) = _media_of(StubMessage(message_id=3, video=object(), size=9_000_000))
    assert media.kind == "video"
    assert not media.is_photo


def test_album_keeps_the_first_id_and_finds_the_caption() -> None:
    """The caption is not always on the first message, but the id always is."""
    album = [
        _photo_message(11, grouped_id=99),
        _photo_message(12, grouped_id=99, text="2 xonali kvartira, Chilonzor"),
        _photo_message(13, grouped_id=99),
    ]

    folded = fold_album(album)

    assert folded.message_id == 11
    assert folded.text == "2 xonali kvartira, Chilonzor"
    assert folded.grouped_id == 99
    assert len(folded.photos) == 3
    assert folded.raw["album_size"] == 3


def test_album_folding_is_order_independent() -> None:
    out_of_order = [
        _photo_message(13, grouped_id=99),
        _photo_message(11, grouped_id=99, text="caption"),
        _photo_message(12, grouped_id=99),
    ]
    assert fold_album(out_of_order).message_id == 11


def test_backfill_folds_albums_and_keeps_singles_apart() -> None:
    history = [
        StubMessage(message_id=1, text="single one"),
        _photo_message(2, grouped_id=50),
        _photo_message(3, grouped_id=50),
        StubMessage(message_id=4, text="single two"),
        _photo_message(5, grouped_id=51),
        _photo_message(6, grouped_id=51),
    ]

    folded = _fold_consecutive_albums(history)

    assert [item.message_id for item in folded] == [1, 2, 4, 5]
    assert len(folded[1].photos) == 2
    assert len(folded[3].photos) == 2


def test_two_albums_are_not_merged_when_adjacent() -> None:
    """Different ``grouped_id`` means different posts, even back to back."""
    folded = _fold_consecutive_albums(
        [
            _photo_message(2, grouped_id=50),
            _photo_message(3, grouped_id=51),
        ]
    )
    assert len(folded) == 2


def test_single_message_album_does_not_become_an_album() -> None:
    (folded,) = _fold_consecutive_albums([_photo_message(9, grouped_id=77)])
    assert folded.message_id == 9
    assert "album_size" not in folded.raw


def test_incoming_message_detects_emptiness() -> None:
    assert StubMessage(message_id=1, text="   ") is not None
    assert _to_incoming(StubMessage(message_id=1, text="   ")).is_empty
    assert not _to_incoming(_photo_message(2)).is_empty
    assert not _to_incoming(StubMessage(message_id=3, text="sotiladi")).is_empty


def test_edited_message_carries_its_edit_date() -> None:
    edited = now_utc()
    incoming = _to_incoming(
        StubMessage(message_id=4, text="sotildi", edit_date=edited, date=edited - timedelta(days=1))
    )
    assert incoming.edited_at == edited
    assert incoming.posted_at < incoming.edited_at


def test_own_messages_are_marked() -> None:
    assert _to_incoming(StubMessage(message_id=5, text="hi", out=True)).from_self


def test_trimmed_raw_does_not_carry_sender_details() -> None:
    """SPEC 13: we keep what we need to debug, not who posted it."""
    raw = _to_incoming(_photo_message(6)).raw
    assert set(raw) == {
        "id",
        "chat_id",
        "grouped_id",
        "date",
        "edit_date",
        "views",
        "forwards",
        "has_media",
    }


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        ("https://t.me/+AbCdEf", "AbCdEf"),
        ("https://t.me/joinchat/AbCdEf", "AbCdEf"),
        ("https://t.me/+AbCdEf?single", "AbCdEf"),
        ("+AbCdEf", "AbCdEf"),
        ("@public_channel", None),
        ("https://t.me/public_channel", None),
    ],
)
def test_invite_hash_extraction(ref: str, expected: str | None) -> None:
    assert _invite_hash(ref) == expected


@pytest.mark.parametrize(
    ("phone", "masked"),
    [
        ("+998901234567", "***4567"),
        ("998 90 123 45 67", "***4567"),
        ("+1 (555) 010-9999", "***9999"),
        ("", "***"),
    ],
)
def test_only_the_last_four_digits_of_a_phone_are_kept(phone: str, masked: str) -> None:
    """SPEC 13 — the full userbot number never reaches the database."""
    assert mask_phone(phone) == masked
