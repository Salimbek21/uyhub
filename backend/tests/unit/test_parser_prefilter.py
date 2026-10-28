"""Deciding whether a post is a listing at all (SPEC 5.1).

The asymmetry matters: a non-listing that slips through shows up as a junk card
someone can report, while a real listing wrongly rejected is inventory nobody
ever learns was missed. These tests lean on the second.
"""

from __future__ import annotations

import pytest

from uyhub.parser.districts import fold
from uyhub.parser.prefilter import MIN_TEXT_LENGTH, RejectReason, prefilter

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "text",
    [
        "3 xonali kvartira Chilonzorda sotiladi. 3/5/9, 75 m2, narxi 65 000 $",
        "Продается 2-комнатная квартира, Юнусабад, 55 кв.м, цена 48000 у.е.",
        "Сдается квартира посуточно, 300 000 сум/сутки",
        "Hovli sotiladi, Sergeli tumani, 6 sotix, kelishiladi",
        "Сотилади 3 хонали квартира, Чилонзор, нархи 64 000 у.е",
        "Ijaraga beriladi 1 xonali kvartira, Mirobod, 400$/oy",
    ],
)
def test_real_listings_are_accepted(text: str) -> None:
    assert prefilter(text).accepted


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("Assalomu alaykum hurmatli guruh a'zolari", RejectReason.CHAT),
        ("Здравствуйте! Кто подскажет?", RejectReason.CHAT),
        ("Kim biladi bu uy qancha turadi?", RejectReason.CHAT),
        ("Chilonzorda 3 xonali kvartira bormi?", RejectReason.CHAT),
        ("ok", RejectReason.TOO_SHORT),
        ("Ремонт под ключ, качественно и недорого, квартира дом офис", RejectReason.STOPWORD),
        ("Сниму квартиру в Чиланзаре, 2 комнаты, до 400 у.е.", RejectReason.STOPWORD),
        ("Kvartira qidiryapman, 2 xonali, Yunusobod tumanida", RejectReason.STOPWORD),
        ("https://t.me/some_channel https://t.me/other_channel", RejectReason.LINKS_ONLY),
    ],
)
def test_non_listings_are_rejected_with_a_reason(text: str, reason: RejectReason) -> None:
    result = prefilter(text)
    assert not result.accepted
    assert result.reason is reason


def test_a_stopword_beats_every_signal() -> None:
    """A renovation ad contains every word a real listing contains."""
    text = "Ремонт под ключ! Квартира, дом, офис. Цена договорная, евроремонт, 65000 у.е."
    result = prefilter(text)
    assert not result.accepted
    assert result.reason is RejectReason.STOPWORD
    assert result.matched == fold("ремонт под ключ")


class TestShortPosts:
    def test_short_text_without_photos_is_dropped(self) -> None:
        assert len("Sotiladi") < MIN_TEXT_LENGTH
        assert prefilter("Sotiladi").reason is RejectReason.TOO_SHORT

    def test_short_text_with_photos_is_kept(self) -> None:
        """A photo carries the listing even when the caption does not."""
        assert prefilter("Sotiladi", has_photos=True).accepted

    def test_empty_text_with_photos_still_needs_a_signal(self) -> None:
        assert not prefilter("   ", has_photos=True).accepted


class TestStructuralSignals:
    def test_rooms_floor_total_is_enough_on_its_own(self) -> None:
        result = prefilter("Yangi e'lon 3/5/9 tez oling arzon narx bor gap")
        assert result.accepted
        assert result.matched == "rooms/floor/total"

    def test_a_price_is_enough_on_its_own(self) -> None:
        result = prefilter("Juda zo'r variant bor, narxi 65 000 $ hammasi joyida")
        assert result.accepted
        assert result.matched == "price"

    def test_a_long_post_with_a_question_mark_and_a_price_is_kept(self) -> None:
        """A real listing that happens to ask something is still a listing."""
        text = (
            "3 xonali kvartira sotiladi Chilonzor tumani, 75 m2, narxi 65 000 $. "
            "Qiziqqanlar bormi? Qo'ng'iroq qiling."
        )
        assert prefilter(text).accepted


def test_the_keyword_files_actually_loaded() -> None:
    """A typo in a data file would silently empty the signal list."""
    result = prefilter("Bu yerda ajoyib hovli bor va narx juda qulay bo'ladi albatta")
    assert result.accepted
    assert result.matched is not None
