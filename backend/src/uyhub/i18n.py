"""User-facing names, in the two languages the product ships in.

CLAUDE.md requires user-facing text to go through i18n keys with `uz` (Latin)
and `ru` translations. District names are the first of those to be needed on
the server: titles are composed in Uzbek, and ``GET /v1/meta`` hands the Mini
App both spellings so the filter sheet can label a district in whichever
language the user picked.

Keeping them here rather than in the parser means there is one spelling of
"Mirzo Ulug'bek" in the codebase, not two that drift.
"""

from __future__ import annotations

from uyhub.models.enums import District

DISTRICT_NAMES_UZ: dict[District, str] = {
    District.BEKTEMIR: "Bektemir",
    District.CHILONZOR: "Chilonzor",
    District.MIROBOD: "Mirobod",
    District.MIRZO_ULUGBEK: "Mirzo Ulug'bek",
    District.OLMAZOR: "Olmazor",
    District.SERGELI: "Sergeli",
    District.SHAYXONTOHUR: "Shayxontohur",
    District.UCHTEPA: "Uchtepa",
    District.YAKKASAROY: "Yakkasaroy",
    District.YASHNOBOD: "Yashnobod",
    District.YUNUSOBOD: "Yunusobod",
    District.YANGIHAYOT: "Yangihayot",
}

DISTRICT_NAMES_RU: dict[District, str] = {
    District.BEKTEMIR: "Бектемирский",
    District.CHILONZOR: "Чиланзарский",
    District.MIROBOD: "Мирабадский",
    District.MIRZO_ULUGBEK: "Мирзо-Улугбекский",
    District.OLMAZOR: "Алмазарский",
    District.SERGELI: "Сергелийский",
    District.SHAYXONTOHUR: "Шайхантахурский",
    District.UCHTEPA: "Учтепинский",
    District.YAKKASAROY: "Яккасарайский",
    District.YASHNOBOD: "Яшнабадский",
    District.YUNUSOBOD: "Юнусабадский",
    District.YANGIHAYOT: "Янгихаётский",
}
