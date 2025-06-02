from datetime import date
from decimal import Decimal

import pytest

from flights.dto import FareVerdict, PriceQuery, PriceQuote
from flights.enums import CabinClass, TripType


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


class TestPriceQuery:
    def test_one_way_rejects_a_return_date(self):
        with pytest.raises(ValueError, match="must not carry a return_date"):
            query(return_date=date(2025, 6, 14))

    def test_round_trip_requires_a_return_date(self):
        with pytest.raises(ValueError, match="needs a return_date"):
            query(trip_type=TripType.ROUND_TRIP)

    def test_cache_key_is_stable_across_instances(self):
        assert query().cache_key == query().cache_key

    def test_cache_key_separates_cabins(self):
        # A business search and an economy search on the same route are two
        # different purchases and must not share a cached answer.
        assert query().cache_key != query(cabin=CabinClass.ECONOMY).cache_key

    def test_cache_key_separates_currencies(self):
        assert query().cache_key != query(currency="EUR").cache_key


class TestPriceQuote:
    def test_rejects_a_non_iso_currency(self):
        with pytest.raises(ValueError, match="ISO 4217"):
            PriceQuote(amount=Decimal("100"), currency="dollars", provider="fixture")

    def test_rejects_a_negative_fare(self):
        with pytest.raises(ValueError, match="cannot be negative"):
            PriceQuote(amount=Decimal("-1"), currency="USD", provider="fixture")

    def test_as_dict_keeps_the_currency_with_the_amount(self):
        payload = PriceQuote(
            amount=Decimal("2570.40"), currency="USD", provider="fixture"
        ).as_dict()
        assert payload["amount"] == "2570.40"
        assert payload["currency"] == "USD"


class TestFareVerdict:
    def test_as_dict_round_trips(self):
        verdict = FareVerdict(
            rating=FareVerdict.PLAUSIBLE, rationale="ok", reviewer="heuristic", cents_per_mile=40.8
        )
        assert verdict.as_dict() == {
            "rating": "plausible",
            "rationale": "ok",
            "reviewer": "heuristic",
            "cents_per_mile": 40.8,
        }
