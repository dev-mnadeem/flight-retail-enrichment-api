"""Read side: browse stored itineraries over JSON."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from flights.models import Flight

from api.schemas import FlightPage, FlightSummary

DEFAULT_LIMIT = 25
MAX_LIMIT = 200

router = APIRouter(prefix="/flights", tags=["flights"])


def _to_summary(flight: Flight) -> FlightSummary:
    return FlightSummary(
        id=flight.flight_id,
        origin=flight.origin,
        destination=flight.destination,
        travel_class=flight.travel_class,
        departure_time=flight.departure_time,
        arrival_time=flight.arrival_time,
        retail_price=str(flight.retail_price) if flight.retail_price is not None else None,
        currency=flight.currency or None,
        price_provider=flight.price_provider or None,
        enriched=flight.enriched,
        fare_review=flight.fare_review,
    )


@router.get("", response_model=FlightPage)
def list_flights(
    origin: str | None = None,
    destination: str | None = None,
    enriched: bool | None = None,
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
) -> FlightPage:
    """Paginated flight list.

    The bound on ``limit`` is the point: the table grows with every payload
    an upstream feed sends, and an unbounded list endpoint is a table scan
    waiting to happen.
    """
    queryset = Flight.objects.all()
    if origin:
        queryset = queryset.filter(origin__iexact=origin)
    if destination:
        queryset = queryset.filter(destination__iexact=destination)
    if enriched is not None:
        queryset = queryset.filter(enriched=enriched)

    total = queryset.count()
    rows = list(queryset[offset : offset + limit])
    return FlightPage(
        items=[_to_summary(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{flight_id}", response_model=FlightSummary)
def get_flight(flight_id: str) -> FlightSummary:
    flight = Flight.objects.filter(flight_id=flight_id).first()
    if flight is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Flight not found")
    return _to_summary(flight)
