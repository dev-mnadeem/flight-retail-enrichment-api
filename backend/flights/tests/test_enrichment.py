from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from flights.dto import FareVerdict, PriceQuery, PriceQuote
from flights.enums import CabinClass, TripType
from flights.models import PriceQuoteCache
from flights.providers.base import (
    PermanentPricingError,
    PriceProvider,
    PriceUnavailable,
    TransientPricingError,
)
from flights.services import EnrichmentService, QuoteCache, build_query

from .conftest import make_flight

pytestmark = pytest.mark.django_db


class CountingProvider(PriceProvider):
    """Records every call so a test can assert the cache actually saved one."""

    name = "counting"

    def __init__(self, amount: str = "2570.40", currency: str = "USD"):
        self.calls: list[PriceQuery] = []
        self._amount = Decimal(amount)
        self._currency = currency

    def fetch(self, query: PriceQuery) -> PriceQuote:
        self.calls.append(query)
        return PriceQuote(amount=self._amount, currency=self._currency, provider=self.name)


class FailingProvider(PriceProvider):
    name = "failing"

    def __init__(self, error: Exception):
        self._error = error

    def fetch(self, query: PriceQuery) -> PriceQuote:
        raise self._error


class TestBuildQuery:
    def test_a_one_way_itinerary_is_priced_one_way(self, flight):
        query = build_query(flight)
        assert query.trip_type is TripType.ONE_WAY
        # Pricing JFK-ATH as a round trip quotes a journey home nobody asked
        # for, and the number comes back looking perfectly valid.
        assert query.return_date is None

    def test_a_returning_itinerary_is_priced_round_trip(self, db):
        flight = make_flight(flight_id="rt", origin="JFK", destination="JFK")
        query = build_query(flight)
        assert query.trip_type is TripType.ROUND_TRIP
        assert query.return_date == date(2025, 6, 14)

    def test_the_cabin_is_carried_through(self, flight):
        assert build_query(flight).cabin is CabinClass.BUSINESS

    def test_codes_are_upper_cased(self, db):
        flight = make_flight(flight_id="lower", origin="jfk", destination="lax")
        query = build_query(flight)
        assert (query.origin, query.destination) == ("JFK", "LAX")


class TestEnrichmentService:
    def test_persists_price_currency_and_provider(self, flight):
        provider = CountingProvider()
        outcome = EnrichmentService(provider=provider).enrich(flight)

        flight.refresh_from_db()
        assert flight.enriched is True
        assert flight.retail_price == Decimal("2570.40")
        assert flight.currency == "USD"
        assert flight.price_provider == "counting"
        assert flight.enriched_at is not None
        assert outcome.quote is not None

    def test_a_second_enrichment_is_served_from_the_cache(self, flight):
        provider = CountingProvider()
        service = EnrichmentService(provider=provider)

        first = service.enrich(flight)
        second = service.enrich(flight)

        assert first.cache_hit is False
        assert second.cache_hit is True
        # The unit saved here is a metered provider search, not a millisecond.
        assert len(provider.calls) == 1

    def test_a_different_cabin_is_not_a_cache_hit(self, flight, db):
        provider = CountingProvider()
        service = EnrichmentService(provider=provider)
        service.enrich(flight)

        economy = make_flight(flight_id="economy-same-route", travel_class=CabinClass.ECONOMY.value)
        outcome = service.enrich(economy)

        assert outcome.cache_hit is False
        assert len(provider.calls) == 2

    def test_an_expired_quote_is_refetched(self, flight):
        provider = CountingProvider()
        service = EnrichmentService(provider=provider, cache=QuoteCache(ttl_seconds=3600))
        service.enrich(flight)

        PriceQuoteCache.objects.all().update(fetched_at=timezone.now() - timedelta(hours=2))
        outcome = service.enrich(flight)

        assert outcome.cache_hit is False
        assert len(provider.calls) == 2

    def test_attaches_a_fare_verdict(self, flight):
        outcome = EnrichmentService(provider=CountingProvider()).enrich(flight)
        assert outcome.verdict is not None
        assert outcome.verdict.rating == FareVerdict.PLAUSIBLE

        flight.refresh_from_db()
        assert flight.fare_review["rating"] == FareVerdict.PLAUSIBLE

    def test_no_leg_distances_means_no_review_and_a_warning(self, db):
        flight = make_flight(flight_id="no-distances", legs=[{"origin": "JFK"}])
        outcome = EnrichmentService(provider=CountingProvider()).enrich(flight)
        assert outcome.verdict is None
        assert "not reviewed" in outcome.warnings[0]

    def test_no_fare_available_marks_the_flight_checked_without_a_price(self, flight):
        provider = FailingProvider(PriceUnavailable("nothing on this route"))
        outcome = EnrichmentService(provider=provider).enrich(flight)

        flight.refresh_from_db()
        assert outcome.quote is None
        assert outcome.warnings == ["nothing on this route"]
        # "Checked, no fare" is an answer. Leaving it unenriched would mean
        # the same dead route is retried forever.
        assert flight.enriched is True
        assert flight.retail_price is None

    def test_a_transient_error_propagates_for_the_task_to_retry(self, flight):
        provider = FailingProvider(TransientPricingError("rate limited", retry_after=45))
        with pytest.raises(TransientPricingError):
            EnrichmentService(provider=provider).enrich(flight)

        flight.refresh_from_db()
        assert flight.enriched is False

    def test_a_permanent_error_propagates_too(self, flight):
        provider = FailingProvider(PermanentPricingError("bad key"))
        with pytest.raises(PermanentPricingError):
            EnrichmentService(provider=provider).enrich(flight)

    def test_a_failed_fetch_leaves_nothing_in_the_cache(self, flight):
        provider = FailingProvider(TransientPricingError("boom"))
        with pytest.raises(TransientPricingError):
            EnrichmentService(provider=provider).enrich(flight)
        assert PriceQuoteCache.objects.count() == 0

    def test_the_stored_currency_is_the_providers_not_ours(self, flight):
        provider = CountingProvider(currency="EUR")
        EnrichmentService(provider=provider).enrich(flight)
        flight.refresh_from_db()
        assert flight.currency == "EUR"


class TestQuoteCache:
    def test_a_miss_returns_none(self, db):
        query = build_query(make_flight(flight_id="miss"))
        assert QuoteCache().get(query) is None

    def test_put_then_get_round_trips(self, db):
        query = build_query(make_flight(flight_id="roundtrip"))
        cache = QuoteCache()
        cache.put(query, PriceQuote(amount=Decimal("99.99"), currency="GBP", provider="x"))
        cached = cache.get(query)
        assert cached is not None
        assert (cached.amount, cached.currency, cached.provider) == (
            Decimal("99.99"),
            "GBP",
            "x",
        )
