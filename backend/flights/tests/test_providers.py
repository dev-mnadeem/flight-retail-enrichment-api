from datetime import date
from decimal import Decimal

import httpx
import pytest

from flights.dto import PriceQuery
from flights.enums import CabinClass, TripType
from flights.providers import (
    FixturePriceProvider,
    PermanentPricingError,
    PriceUnavailable,
    SerpApiPriceProvider,
    TransientPricingError,
    available_providers,
    get_provider,
)
from flights.providers.serpapi import DEFAULT_RATE_LIMIT_BACKOFF_SECONDS


def query(**overrides) -> PriceQuery:
    defaults = {
        "origin": "JFK",
        "destination": "ATH",
        "outbound_date": date(2025, 6, 13),
        "cabin": CabinClass.BUSINESS,
        "trip_type": TripType.ONE_WAY,
    }
    defaults.update(overrides)
    return PriceQuery(**defaults)


def stub_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


class TestRegistry:
    def test_lists_both_adapters(self):
        assert available_providers() == ("fixture", "serpapi")

    def test_default_is_the_offline_provider(self):
        assert get_provider().name == "fixture"

    def test_unknown_name_is_permanent_not_transient(self):
        with pytest.raises(PermanentPricingError, match="Unknown price provider"):
            get_provider("quantum-airlines")


class TestFixtureProvider:
    def test_business_costs_more_than_economy_on_the_same_route(self):
        provider = FixturePriceProvider()
        business = provider.fetch(query()).amount
        economy = provider.fetch(query(cabin=CabinClass.ECONOMY)).amount
        assert business > economy

    def test_known_route_is_deterministic(self):
        provider = FixturePriceProvider()
        assert provider.fetch(query()).amount == provider.fetch(query()).amount

    def test_business_jfk_ath_one_way(self):
        # 612.00 economy base x 4.20 business multiplier.
        assert FixturePriceProvider().fetch(query()).amount == Decimal("2570.40")

    def test_round_trip_costs_more_than_one_way(self):
        provider = FixturePriceProvider()
        one_way = provider.fetch(query())
        round_trip = provider.fetch(
            query(trip_type=TripType.ROUND_TRIP, return_date=date(2025, 6, 20))
        )
        assert round_trip.amount > one_way.amount

    def test_unknown_route_is_not_an_error(self):
        with pytest.raises(PriceUnavailable):
            FixturePriceProvider().fetch(query(destination="ZZZ"))

    def test_quote_carries_its_currency(self):
        assert FixturePriceProvider().fetch(query()).currency == "USD"


class TestSerpApiProvider:
    def test_empty_key_is_rejected_at_construction(self):
        with pytest.raises(PermanentPricingError, match="SERPAPI_KEY is empty"):
            SerpApiPriceProvider(api_key="")

    def test_sends_cabin_and_trip_type(self):
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(request.url.params)
            return httpx.Response(200, json={"best_flights": [{"price": 2400}]})

        SerpApiPriceProvider(api_key="k", client=stub_client(handler)).fetch(query())
        # Business is travel_class 3, one way is type 2. Omitting either
        # silently prices a different journey.
        assert seen["travel_class"] == "3"
        assert seen["type"] == "2"
        assert "return_date" not in seen

    def test_round_trip_sends_a_return_date(self):
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(request.url.params)
            return httpx.Response(200, json={"best_flights": [{"price": 2400}]})

        SerpApiPriceProvider(api_key="k", client=stub_client(handler)).fetch(
            query(trip_type=TripType.ROUND_TRIP, return_date=date(2025, 6, 20))
        )
        assert seen["type"] == "1"
        assert seen["return_date"] == "2025-06-20"

    def test_empty_best_flights_falls_through_to_other_flights(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"best_flights": [], "other_flights": [{"price": 1990}]}
            )

        quote = SerpApiPriceProvider(api_key="k", client=stub_client(handler)).fetch(query())
        assert quote.amount == Decimal("1990")

    def test_partial_response_with_no_price_is_price_unavailable(self):
        # The list is present, the entries are present, the price key is not.
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"best_flights": [{"airline": "MS"}]})

        with pytest.raises(PriceUnavailable):
            SerpApiPriceProvider(api_key="k", client=stub_client(handler)).fetch(query())

    def test_missing_keys_entirely_is_price_unavailable(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"search_metadata": {"status": "Success"}})

        with pytest.raises(PriceUnavailable):
            SerpApiPriceProvider(api_key="k", client=stub_client(handler)).fetch(query())

    def test_unparseable_price_is_permanent_not_transient(self):
        # Retrying will return the same garbage, so it must not be retried.
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"best_flights": [{"price": "call us"}]})

        with pytest.raises(PermanentPricingError, match="not a number"):
            SerpApiPriceProvider(api_key="k", client=stub_client(handler)).fetch(query())

    def test_error_field_on_a_200_is_permanent(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"error": "Invalid API key"})

        with pytest.raises(PermanentPricingError, match="Invalid API key"):
            SerpApiPriceProvider(api_key="k", client=stub_client(handler)).fetch(query())

    def test_rate_limit_honours_retry_after(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, headers={"Retry-After": "90"}, json={})

        with pytest.raises(TransientPricingError) as excinfo:
            SerpApiPriceProvider(api_key="k", client=stub_client(handler)).fetch(query())
        assert excinfo.value.retry_after == 90.0

    def test_rate_limit_without_a_header_uses_the_default_backoff(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={})

        with pytest.raises(TransientPricingError) as excinfo:
            SerpApiPriceProvider(api_key="k", client=stub_client(handler)).fetch(query())
        assert excinfo.value.retry_after == DEFAULT_RATE_LIMIT_BACKOFF_SECONDS

    def test_server_error_is_transient(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={})

        with pytest.raises(TransientPricingError):
            SerpApiPriceProvider(api_key="k", client=stub_client(handler)).fetch(query())

    def test_client_error_is_permanent(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, text="bad request")

        with pytest.raises(PermanentPricingError):
            SerpApiPriceProvider(api_key="k", client=stub_client(handler)).fetch(query())

    def test_timeout_is_transient(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("too slow", request=request)

        with pytest.raises(TransientPricingError, match="timed out"):
            SerpApiPriceProvider(api_key="k", client=stub_client(handler)).fetch(query())

    def test_currency_comes_from_the_response_not_the_request(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "search_parameters": {"currency": "EUR"},
                    "best_flights": [{"price": 2100}],
                },
            )

        quote = SerpApiPriceProvider(api_key="k", client=stub_client(handler)).fetch(query())
        assert quote.currency == "EUR"
