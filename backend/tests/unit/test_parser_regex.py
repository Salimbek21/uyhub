"""Regex extraction of prices, rooms, floors and areas (SPEC 5.2)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from uyhub.models.enums import (
    BuildingType,
    Currency,
    DealType,
    PricePeriod,
    PropertyType,
    Renovation,
)
from uyhub.parser.regex_extract import (
    best_price,
    find_area_m2,
    find_building_type,
    find_deal_type,
    find_land_sotix,
    find_period,
    find_prices,
    find_property_type,
    find_renovation,
    find_rooms_and_floors,
    is_negotiable,
    parse_number,
)

pytestmark = pytest.mark.unit


class TestNumbers:
    """`65 000`, `65.000` and `1,2` all have to come out right."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("65000", "65000"),
            ("65 000", "65000"),
            ("65 000", "65000"),  # non-breaking space, as Telegram inserts
            ("65.000", "65000"),
            ("65,000", "65000"),
            ("1 234 567", "1234567"),
            ("1,2", "1.2"),
            ("1.2", "1.2"),
            ("4,5", "4.5"),
            ("1.234,5", "1234.5"),
        ],
    )
    def test_separators(self, raw: str, expected: str) -> None:
        assert parse_number(raw) == Decimal(expected)

    def test_empty_is_none(self) -> None:
        assert parse_number("") is None
        assert parse_number("   ") is None


class TestPrices:
    @pytest.mark.parametrize(
        ("text", "amount", "currency"),
        [
            ("narxi 65 000$", "65000", Currency.USD),
            ("$45000", "45000", Currency.USD),
            ("65000 у.е.", "65000", Currency.USD),
            ("65000 y.e.", "65000", Currency.USD),
            ("65 ming $", "65000", Currency.USD),
            ("65k", "65000", Currency.USD),
            ("58 000 dollar", "58000", Currency.USD),
            ("650 mln so'm", "650000000", Currency.UZS),
            ("650 млн сум", "650000000", Currency.UZS),
            ("1,2 mlrd сум", "1200000000", Currency.UZS),
            ("780 000 000 сум", "780000000", Currency.UZS),
        ],
    )
    def test_written_forms(self, text: str, amount: str, currency: Currency) -> None:
        price = best_price(text)
        assert price is not None
        assert price.amount == Decimal(amount)
        assert price.currency is currency

    def test_a_bare_number_is_not_a_price(self) -> None:
        """Without a currency or a multiplier there is nothing to anchor on."""
        assert find_prices("3 xonali 75 kv") == []

    def test_currency_is_inferred_from_magnitude_when_unstated(self) -> None:
        """Dollars and so'm do not overlap in the range a flat is priced in."""
        inferred = best_price("5 mln/месяц")
        assert inferred is not None
        assert inferred.currency is Currency.UZS
        assert not inferred.explicit_currency

    def test_an_explicit_currency_beats_a_larger_inferred_one(self) -> None:
        price = best_price("maydoni 75 kv, 3 mln ta g'isht, narxi 65 000 $")
        assert price is not None
        assert price.amount == Decimal(65_000)
        assert price.explicit_currency

    def test_no_price_is_none(self) -> None:
        assert best_price("narxi kelishiladi") is None


class TestPeriod:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("400$/oy", PricePeriod.MONTH),
            ("500 у.е./мес", PricePeriod.MONTH),
            ("oyiga 700 y.e.", PricePeriod.MONTH),
            ("600 у.е. в месяц", PricePeriod.MONTH),
            ("300 000 сум/сутки", PricePeriod.DAY),
            ("сдается посуточно", PricePeriod.DAY),
            ("narxi 65 000 $", None),
        ],
    )
    def test_period(self, text: str, expected: PricePeriod | None) -> None:
        assert find_period(text) == expected


class TestRoomsAndFloors:
    def test_the_rft_triple(self) -> None:
        found = find_rooms_and_floors("3/5/9")
        assert (found.rooms, found.floor, found.floors_total) == (3, 5, 9)

    def test_a_spelled_room_count_beats_the_triple(self) -> None:
        """ "3 xonali ... 8/9/9" — the writer who spelled it out meant it."""
        found = find_rooms_and_floors("3 xonali kvartira 8/9/9")
        assert found.rooms == 3
        assert (found.floor, found.floors_total) == (9, 9)

    @pytest.mark.parametrize(
        ("text", "rooms"),
        [
            ("3 xonali", 3),
            ("2-комнатная", 2),
            ("4 комнаты", 4),
            ("3 комн", 3),
            ("2 хонали", 2),
            ("Xonalar: 2", 2),
            ("Комнат: 2", 2),
            ("Количество комнат: 3", 3),
        ],
    )
    def test_room_counts(self, text: str, rooms: int) -> None:
        assert find_rooms_and_floors(text).rooms == rooms

    def test_a_pair_without_rooms_is_floor_and_total(self) -> None:
        found = find_rooms_and_floors("5/9")
        assert found.rooms is None
        assert (found.floor, found.floors_total) == (5, 9)

    def test_floor_and_total_from_words(self) -> None:
        found = find_rooms_and_floors("6-qavat, jami 12 qavatli")
        assert (found.floor, found.floors_total) == (6, 12)

    def test_total_stated_as_out_of(self) -> None:
        found = find_rooms_and_floors("6 этаж из 12")
        assert (found.floor, found.floors_total) == (6, 12)

    def test_a_newline_does_not_join_a_number_to_the_next_label(self) -> None:
        """ "Комнат: 2\\nЭтаж: 7/9" must not read the 2 as the floor."""
        found = find_rooms_and_floors("Комнат: 2\nЭтаж: 7/9")
        assert found.rooms == 2
        assert (found.floor, found.floors_total) == (7, 9)


class TestAreas:
    @pytest.mark.parametrize(
        "text", ["75 m2", "75 м2", "75 кв.м", "75 кв м", "75 м²", "75 m²", "75 kv"]
    )
    def test_area_forms(self, text: str) -> None:
        assert find_area_m2(text) == Decimal(75)

    @pytest.mark.parametrize("text", ["6 sotix", "6 соток", "6 сотки", "6 сотих"])
    def test_sotix_forms(self, text: str) -> None:
        assert find_land_sotix(text) == Decimal(6)

    def test_fractional_sotix(self) -> None:
        assert find_land_sotix("4,5 сотки") == Decimal("4.5")

    def test_absent_is_none(self) -> None:
        assert find_area_m2("3 xonali") is None
        assert find_land_sotix("3 xonali") is None


class TestCategories:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("kvartira sotiladi", DealType.SALE),
            ("продается квартира", DealType.SALE),
            ("сотилади", DealType.SALE),
            ("ijaraga beriladi", DealType.RENT),
            ("сдается квартира", DealType.RENT),
            ("сдаю в аренду", DealType.RENT),
            ("3 xonali kvartira", None),
        ],
    )
    def test_deal_type(self, text: str, expected: DealType | None) -> None:
        assert find_deal_type(text) == expected

    def test_a_post_offering_both_is_a_sale(self) -> None:
        assert find_deal_type("sotiladi yoki ijaraga beriladi") is DealType.SALE

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("3 xonali kvartira", PropertyType.APARTMENT),
            ("2-комнатная квартира", PropertyType.APARTMENT),
            ("hovli sotiladi", PropertyType.HOUSE),
            ("продается частный дом", PropertyType.HOUSE),
            ("yer uchastka", PropertyType.LAND),
            ("продается участок", PropertyType.LAND),
            ("ofis ijaraga", PropertyType.COMMERCIAL),
            ("аренда офиса", PropertyType.COMMERCIAL),
            ("продается склад", PropertyType.COMMERCIAL),
        ],
    )
    def test_property_type(self, text: str, expected: PropertyType) -> None:
        assert find_property_type(text) is expected

    def test_panel_dom_is_an_apartment_not_a_house(self) -> None:
        """`дом` means building as often as it means house."""
        text = "Сдается 2-комнатная квартира, панельный дом"
        assert find_property_type(text) is PropertyType.APARTMENT

    def test_a_house_with_rooms_is_still_a_house(self) -> None:
        assert find_property_type("Hovlida 4 xonali uy sotiladi") is PropertyType.HOUSE

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("evro remont", Renovation.EURO),
            ("после евроремонта", Renovation.EURO),
            ("с косметическим ремонтом", Renovation.COSMETIC),
            ("хорошим ремонтом", Renovation.GOOD),
            ("требует ремонта", Renovation.NEEDS_REPAIR),
            ("без ремонта", Renovation.NONE),
            ("qora suvoq", Renovation.NONE),
            ("3 xonali", Renovation.UNKNOWN),
        ],
    )
    def test_renovation(self, text: str, expected: Renovation) -> None:
        assert find_renovation(text) is expected

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("g'ishtli uy", BuildingType.BRICK),
            ("кирпичном доме", BuildingType.BRICK),
            ("панельном доме", BuildingType.PANEL),
            ("в монолитном доме", BuildingType.MONOLITH),
            ("обычный дом", BuildingType.UNKNOWN),
        ],
    )
    def test_building_type(self, text: str, expected: BuildingType) -> None:
        assert find_building_type(text) is expected

    def test_domashniy_is_not_a_house(self) -> None:
        """A term without a wildcard must match a whole word."""
        assert find_property_type("домашний интернет") is None

    @pytest.mark.parametrize(
        "text",
        ["narxi kelishiladi", "kelishamiz", "келишамиз", "цена договорная", "торг уместен"],
    )
    def test_negotiable(self, text: str) -> None:
        assert is_negotiable(text)

    def test_not_negotiable(self) -> None:
        assert not is_negotiable("narxi 65 000 $")
