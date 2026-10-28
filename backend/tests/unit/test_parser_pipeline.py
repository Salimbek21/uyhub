"""The parser end to end on a string, plus district matching and the golden set.

`parse` is a pure function, so the whole pipeline — prefilter, extraction,
normalisation — is testable without a database, a queue or a network.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from uyhub.core.config import Settings, get_settings
from uyhub.models.enums import DealType, District, PropertyType, RawMessageStatus
from uyhub.parser.districts import all_aliases, detect_district, fold
from uyhub.parser.pipeline import default_extractor, parse

pytestmark = pytest.mark.unit

RATE = Decimal(12_000)


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("PHONE_HASH_KEY", "pipeline-test-key")
    monkeypatch.setenv("LLM_ENABLED", "false")
    get_settings.cache_clear()
    return get_settings()


class TestDistricts:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Chilonzor tumanida", District.CHILONZOR),
            ("Chilonzorda sotiladi", District.CHILONZOR),
            ("Чиланзарский район", District.CHILONZOR),
            ("в Чиланзаре", District.CHILONZOR),
            ("Юнусабадский район", District.YUNUSOBOD),
            ("Yunusobodda", District.YUNUSOBOD),
            ("Mirzo Ulug'bek", District.MIRZO_ULUGBEK),
            ("Мирзо-Улугбекский", District.MIRZO_ULUGBEK),
            ("Учтепинском районе", District.UCHTEPA),
            ("Яшнабадском районе", District.YASHNOBOD),
            ("Хамза тумани", District.YASHNOBOD),
            ("в Бектемире", District.BEKTEMIR),
            ("ЯНГИХАЁТ", District.YANGIHAYOT),
        ],
    )
    def test_names_in_every_script_and_case(self, text: str, expected: District) -> None:
        match = detect_district(text)
        assert match is not None
        assert match.district is expected
        assert not match.by_landmark

    def test_a_landmark_identifies_a_district(self) -> None:
        match = detect_district("Chorsu bozori yonida")
        assert match is not None
        assert match.district is District.SHAYXONTOHUR
        assert match.by_landmark

    def test_two_districts_means_no_district(self) -> None:
        """An unlabelled listing is less filterable; a mislabelled one is wrong."""
        assert detect_district("Chilonzor va Yunusobod oralig'ida") is None

    def test_no_district_is_none(self) -> None:
        assert detect_district("Toshkentda kvartira sotiladi") is None

    def test_every_canonical_id_is_reachable(self) -> None:
        """A district missing from the YAML could never be matched."""
        reachable = set(all_aliases().values())
        assert reachable == set(District)

    @pytest.mark.parametrize(
        ("left", "right"),
        [("Mirzo Ulug'bek", "mirzo ulugbek"), ("Mirzo-Ulug`bek", "MIRZO ULUGBEK")],
    )
    def test_folding_ignores_apostrophes_punctuation_and_case(self, left: str, right: str) -> None:
        assert fold(left) == fold(right)


class TestPipeline:
    def test_a_full_uzbek_listing(self, settings: Settings) -> None:
        text = (
            "SOTILADI\n3 xonali kvartira, Chilonzor tumani\n3/5/9, 75 m2\n"
            "Yevro remont, g'ishtli uy\nNarxi: 65 000 $ kelishiladi\n"
            "Tel: +998 90 123 45 67"
        )
        result = parse(text, photo_count=4, uzs_per_usd=RATE, settings=settings)
        extraction = result.extraction

        assert result.status is RawMessageStatus.PARSED
        assert extraction is not None
        assert extraction.deal_type is DealType.SALE
        assert extraction.property_type is PropertyType.APARTMENT
        assert extraction.rooms == 3
        assert (extraction.floor, extraction.floors_total) == (5, 9)
        assert extraction.area_m2 == Decimal(75)
        assert extraction.price_usd == Decimal("65000.00")
        assert extraction.district is District.CHILONZOR
        assert extraction.negotiable
        assert extraction.title == "3 xonali kvartira, Chilonzor, 75 m²"
        assert len(extraction.phone_hashes) == 1

    def test_a_uzs_price_becomes_usd(self, settings: Settings) -> None:
        text = "Продается 2-комнатная квартира, Юнусабад, 780 000 000 сум. 90 123 45 67"
        result = parse(text, uzs_per_usd=RATE, settings=settings)
        assert result.extraction is not None
        assert result.extraction.price_usd == Decimal("65000.00")

    def test_a_rejected_post_has_no_extraction(self, settings: Settings) -> None:
        result = parse("Assalomu alaykum hurmatli guruh", settings=settings)
        assert result.status is RawMessageStatus.REJECTED_PREFILTER
        assert result.extraction is None
        assert result.reject_reason == "chat"
        assert result.rejected

    def test_several_properties_in_one_post_are_dropped(self, settings: Settings) -> None:
        """SPEC 6.6: do not try to split them in the MVP."""
        text = (
            "Sotiladi 2 ta kvartira:\n"
            "1) Chilonzor, 2 xonali, 48000$, tel 90 111 22 33\n"
            "2) Sergeli, 3 xonali, 56000$, tel 93 444 55 66"
        )
        result = parse(text, settings=settings)
        assert result.status is RawMessageStatus.REJECTED_LLM
        assert result.reject_reason == "multi_listing"

    def test_two_contact_numbers_alone_do_not_trigger_multi_listing(
        self, settings: Settings
    ) -> None:
        """Listing two phone numbers is ordinary and says nothing about count."""
        text = (
            "3 xonali kvartira sotiladi Chilonzor, 75 m2, narxi 65 000 $. "
            "Tel: 90 111 22 33 yoki 93 444 55 66"
        )
        result = parse(text, settings=settings)
        assert result.status is RawMessageStatus.PARSED

    def test_the_deal_type_is_inferred_from_the_price_when_unstated(
        self, settings: Settings
    ) -> None:
        text = "Яшнабадский район, Тузель. 3-комнатная квартира, 71 м2. 64 000 у.е. 93 777 11 22"
        result = parse(text, uzs_per_usd=RATE, settings=settings)
        assert result.extraction is not None
        assert result.extraction.deal_type is DealType.SALE

    def test_an_ambiguous_post_leaves_the_deal_type_null(self, settings: Settings) -> None:
        text = "Бектемир, 3-комнатная, 5/5, 64 м2, панельный, цена договорная. 99 777 11 00"
        result = parse(text, uzs_per_usd=RATE, settings=settings)
        assert result.extraction is not None
        assert result.extraction.deal_type is None

    def test_rent_defaults_to_a_monthly_price(self, settings: Settings) -> None:
        text = "Ijaraga beriladi 1 xonali kvartira Mirobod 400 y.e. 94 555 66 77"
        result = parse(text, settings=settings)
        assert result.extraction is not None
        assert result.extraction.price_period is not None
        assert result.extraction.price_period.value == "month"

    def test_the_parser_version_is_recorded(self, settings: Settings) -> None:
        result = parse("3 xonali kvartira sotiladi, 65 000 $", settings=settings)
        assert result.extraction is not None
        assert result.extraction.parser_version == settings.parser_version

    def test_the_default_extractor_is_the_regex_one(self, settings: Settings) -> None:
        assert default_extractor(settings).name == "regex"


class TestRealPostFormats:
    """Patterns taken from the first 47 real posts the collector brought in.

    Every one of these was a wrong answer before it was a test. They are kept
    separate from the synthetic fixtures because they are the only part of the
    suite that is evidence rather than invention.
    """

    REALTOR_POST = (
        "#Kvartira\n"
        "Kimlarga: Oilaga ✅\n"
        "Manzil: Chilonzor, Globus Torgoviy Sentr Yonida ✅\n"
        "Xonalar Soni: 5Xona 3/5\n"
        "Yevro Lux Remont 👔\n"
        "Narx: 1400$ _ 1200$ Ga Oberladi 👕\n"
        "TEL. 90 123 45 67 / 93 111 22 33"
    )

    def test_an_asking_price_and_a_floor_is_one_listing(self, settings: Settings) -> None:
        """Half of the first real batch was rejected as multi_listing over this.

        `Narx: 1400$ _ 1200$ Ga Oberladi` is one flat with a price the realtor
        will come down from, and `TEL. x / y` is one realtor with two numbers.
        """
        result = parse(self.REALTOR_POST, photo_count=2, settings=settings)

        assert result.status is RawMessageStatus.PARSED
        assert result.extraction is not None
        assert result.extraction.rooms == 5

    def test_the_advertised_price_is_the_one_kept(self, settings: Settings) -> None:
        """Showing the floor would under-promise and surprise the buyer later."""
        result = parse(self.REALTOR_POST, settings=settings)
        assert result.extraction is not None
        assert result.extraction.price_amount == Decimal(1400)

    def test_a_price_with_no_verb_below_the_sale_floor_is_rent(self, settings: Settings) -> None:
        """These posts name no verb at all; the price is the only signal."""
        result = parse(self.REALTOR_POST, settings=settings)
        assert result.extraction is not None
        assert result.extraction.deal_type is DealType.RENT

    def test_a_price_with_no_verb_above_the_sale_floor_is_a_sale(self, settings: Settings) -> None:
        text = "Chilonzor, 3 xonali, 3/5/9, Narx: 65 000$. TEL. 90 123 45 67"
        result = parse(text, settings=settings)
        assert result.extraction is not None
        assert result.extraction.deal_type is DealType.SALE

    def test_two_different_room_counts_is_several_listings(self, settings: Settings) -> None:
        text = (
            "Kvartiralar:\n"
            "Chilonzor 2 xonali 48000$ tel 90 111 22 33\n"
            "Sergeli 3 xonali 56000$ tel 93 444 55 66"
        )
        result = parse(text, settings=settings)
        assert result.reject_reason == "multi_listing"

    def test_a_numbered_list_with_prices_is_several_listings(self, settings: Settings) -> None:
        text = "Sotiladi:\n1) Chilonzor kvartira 48000$\n2) Sergeli kvartira 56000$"
        result = parse(text, settings=settings)
        assert result.reject_reason == "multi_listing"

    def test_the_squared_metre_format(self, settings: Settings) -> None:
        """Real posts write `( 100² Metr Kotta Kvartira )`."""
        text = "#Kvartira Mirobod 2Xona 6/10 ( 100² Metr ) Narx: 650$ TEL. 90 123 45 67"
        result = parse(text, settings=settings)
        assert result.extraction is not None
        assert result.extraction.area_m2 == Decimal(100)

    def test_an_abbreviated_district_name(self, settings: Settings) -> None:
        text = "#Kvartira Manzil: M.Ulugbek Metro Yonida. 2Xona 6/10. Narx: 1000$"
        result = parse(text, settings=settings)
        assert result.extraction is not None
        assert result.extraction.district is District.MIRZO_ULUGBEK

    def test_the_labelled_room_format(self, settings: Settings) -> None:
        """`Xonalar Soni: 2Xona 6/10` — a label, a count and a floor pair."""
        result = parse(
            "#Kvartira Xonalar Soni: 2Xona 6/10 Narx: 1000$ TEL. 90 123 45 67",
            settings=settings,
        )
        assert result.extraction is not None
        assert result.extraction.rooms == 2
        assert (result.extraction.floor, result.extraction.floors_total) == (6, 10)

    def test_enabling_the_llm_without_one_built_fails_loudly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Better than silently running the regex extractor and calling it an LLM."""
        monkeypatch.setenv("LLM_ENABLED", "true")
        get_settings.cache_clear()
        with pytest.raises(NotImplementedError, match="LLM_ENABLED"):
            default_extractor(get_settings())
