"""Fixtures shared by the flights tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from flights.enums import CabinClass
from flights.models import Flight

#: A fixed departure keeps the derived PriceQuery -- and therefore the cache
#: key -- identical on every run.
DEPARTURE = datetime(2025, 6, 13, 12, 55, tzinfo=UTC)


def make_flight(**overrides) -> Flight:
    defaults = {
        "flight_id": "20250613-MS-MS986-MS747",
        "travel_class": CabinClass.BUSINESS.value,
        "origin": "JFK",
        "destination": "ATH",
        "departure_time": DEPARTURE,
        "arrival_time": DEPARTURE + timedelta(hours=23, minutes=15),
        "flight_numbers": ["MS986", "MS747"],
        "legs": [
            {"origin": "JFK", "destination": "CAI", "flight_number": "MS986", "distance": 5614},
            {"origin": "CAI", "destination": "ATH", "flight_number": "MS747", "distance": 688},
        ],
        "last_seen": DEPARTURE - timedelta(days=15),
    }
    defaults.update(overrides)
    return Flight.objects.create(**defaults)


@pytest.fixture
def flight(db) -> Flight:
    return make_flight()


@pytest.fixture
def economy_flight(db) -> Flight:
    return make_flight(
        flight_id="20250613-AA-AA123",
        travel_class=CabinClass.ECONOMY.value,
        origin="JFK",
        destination="LAX",
        legs=[{"origin": "JFK", "destination": "LAX", "flight_number": "AA123", "distance": 2475}],
    )
