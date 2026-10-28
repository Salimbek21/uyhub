"""The CBU exchange-rate client (SPEC 6.3).

Every response here is recorded, not fetched: the suite must never depend on
cbu.uz being up, and CLAUDE.md forbids tests that call real external services.
The payload shape is copied from a real response.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx
import pytest
import respx

from uyhub.core.config import Settings, get_settings
from uyhub.core.errors import DependencyUnavailableError
from uyhub.models.enums import Currency
from uyhub.rates import cbu
from uyhub.rates.cbu import CbuRateProvider

pytestmark = pytest.mark.unit

URL = "https://cbu.uz/uz/arkhiv-kursov-valyut/json/USD/"

REAL_PAYLOAD = [
    {
        "id": 1,
        "Code": "840",
        "Ccy": "USD",
        "CcyNm_UZ": "AQSH dollari",
        "Nominal": "1",
        "Rate": "11861.96",
        "Diff": "23.04",
        "Date": "27.10.2026",
    }
]


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("CBU_API_URL", "https://cbu.uz/uz/arkhiv-kursov-valyut/json/")
    # The real backoff is seconds; the retry behaviour is what is under test,
    # not the waiting.
    monkeypatch.setattr(cbu, "BACKOFF_BASE_SECONDS", 0.001)
    get_settings.cache_clear()
    return get_settings()


@respx.mock
async def test_a_real_payload_is_parsed(settings: Settings) -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json=REAL_PAYLOAD))

    rate = await CbuRateProvider(settings).fetch()

    assert rate.currency is Currency.USD
    assert rate.rate_uzs == Decimal("11861.96")
    assert rate.on_date == date(2026, 10, 27)


@respx.mock
async def test_nominal_is_applied(settings: Settings) -> None:
    """`Nominal` is 1 for USD but 100 or 1000 for others; ignoring it is a
    hundredfold error."""
    payload = [{**REAL_PAYLOAD[0], "Nominal": "100", "Rate": "1000"}]
    respx.get(URL).mock(return_value=httpx.Response(200, json=payload))

    rate = await CbuRateProvider(settings).fetch()

    assert rate.rate_uzs == Decimal(10)


@respx.mock
async def test_a_transient_failure_is_retried(settings: Settings) -> None:
    route = respx.get(URL).mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(200, json=REAL_PAYLOAD),
        ]
    )

    rate = await CbuRateProvider(settings).fetch()

    assert route.call_count == 2
    assert rate.rate_uzs == Decimal("11861.96")


@respx.mock
async def test_persistent_failure_raises_a_dependency_error(settings: Settings) -> None:
    respx.get(URL).mock(return_value=httpx.Response(500))

    with pytest.raises(DependencyUnavailableError) as excinfo:
        await CbuRateProvider(settings).fetch()

    assert excinfo.value.dependency == "cbu"


@respx.mock
async def test_an_empty_response_is_an_error_not_a_zero_rate(settings: Settings) -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json=[]))

    with pytest.raises(DependencyUnavailableError, match="empty"):
        await CbuRateProvider(settings).fetch()


@respx.mock
async def test_a_changed_payload_shape_is_an_error(settings: Settings) -> None:
    """Better to fail loudly than to store a rate read out of the wrong field."""
    respx.get(URL).mock(return_value=httpx.Response(200, json=[{"Ccy": "USD"}]))

    with pytest.raises(DependencyUnavailableError, match="unexpected payload"):
        await CbuRateProvider(settings).fetch()


@respx.mock
async def test_a_non_positive_rate_is_refused(settings: Settings) -> None:
    payload = [{**REAL_PAYLOAD[0], "Rate": "0"}]
    respx.get(URL).mock(return_value=httpx.Response(200, json=payload))

    with pytest.raises(DependencyUnavailableError, match="non-positive"):
        await CbuRateProvider(settings).fetch()
