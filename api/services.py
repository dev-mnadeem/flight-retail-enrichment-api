"""Translation between the wire schema and the Django models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from flights.enums import CabinClass
from flights.models import Flight

from api.schemas import FlightData


def _serialise_leg(leg: Any) -> dict[str, Any]:
    return {
        key: (value.isoformat() if isinstance(value, datetime) else value)
        for key, value in leg.model_dump().items()
    }


def save_flight(payload: FlightData) -> Flight:
    """Insert or refresh the itinerary row for one payload.

    Resubmitting an itinerary resets it to unenriched: the point of sending
    it again is that something about it may have changed. The price itself
    is not thrown away here -- the quote cache decides whether the provider
    is called again, which is what stops a re-submission from costing a
    second metered search.
    """
    flight, _ = Flight.objects.update_or_create(
        flight_id=payload.id,
        defaults={
            "travel_class": CabinClass.parse(payload.travel_class).value,
            "origin": payload.origin,
            "destination": payload.destination,
            "departure_time": payload.departure_time,
            "arrival_time": payload.arrival_time,
            "flight_numbers": payload.flight_numbers,
            "legs": [_serialise_leg(leg) for leg in payload.legs],
            "last_seen": payload.last_seen,
            "enriched": False,
        },
    )
    return flight
