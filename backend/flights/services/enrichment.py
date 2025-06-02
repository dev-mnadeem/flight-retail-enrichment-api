"""The enrichment pipeline.

Turn a stored ``Flight`` into a priced one: build the query, get a quote
(from cache or a provider), review it, persist. The Celery task owns retry
policy and nothing else -- everything here is callable straight from a test
with no broker running.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime

from django.db import transaction
from django.utils import timezone

from ..dto import EnrichmentOutcome, PriceQuery
from ..enums import TripType
from ..models import Flight
from ..providers import PermanentPricingError, PriceProvider, PriceUnavailable, get_provider
from ..review import FareReviewer, get_reviewer
from .quotes import QuoteCache

logger = logging.getLogger(__name__)


def build_query(flight: Flight, currency: str = "USD") -> PriceQuery:
    """Derive the pricing query from a stored itinerary.

    Two things here are easy to get wrong and expensive to get wrong. An
    itinerary that does not return to its origin is a one-way search, so it
    must not carry a return date -- pricing JFK-ATH as a round trip prices a
    journey home that nobody asked for. And the cabin has to be sent: a
    provider given no cabin quotes economy, so a business itinerary comes
    back at roughly a quarter of its real fare and looks entirely valid.

    A round trip's top-level origin and destination are the same airport, so
    the place the passenger is actually flying to has to come from the legs.
    """
    origin = flight.origin.upper()
    outbound = timezone.localtime(flight.departure_time).date()

    if origin != flight.destination.upper():
        return PriceQuery(
            origin=origin,
            destination=flight.destination.upper(),
            outbound_date=outbound,
            cabin=flight.cabin,
            trip_type=TripType.ONE_WAY,
            currency=currency,
        )

    destination, return_date = _turnaround(flight)
    return PriceQuery(
        origin=origin,
        destination=destination,
        outbound_date=outbound,
        cabin=flight.cabin,
        trip_type=TripType.ROUND_TRIP,
        currency=currency,
        return_date=return_date,
    )


def _turnaround(flight: Flight) -> tuple[str, date]:
    """Where a round trip turns back, and the date the return leg departs.

    The stay at the destination is the longest time on the ground between
    two consecutive legs; a connection is hours, a stay is days. Without
    leg times there is no way to tell the two apart, and guessing would
    send the provider a search for the wrong city.
    """
    legs = [leg for leg in flight.legs or [] if isinstance(leg, dict)]
    if len(legs) < _MIN_ROUND_TRIP_LEGS:
        raise PermanentPricingError(
            f"Round trip {flight.flight_id} needs at least two legs to find its destination"
        )

    ground_times = []
    for arriving, departing in zip(legs, legs[1:], strict=False):
        landed = _parse_leg_time(arriving.get("arrival_time"))
        leaves = _parse_leg_time(departing.get("departure_time"))
        if landed is None or leaves is None:
            raise PermanentPricingError(
                f"Round trip {flight.flight_id} has legs without times, "
                "so its destination cannot be told apart from a connection"
            )
        ground_times.append((leaves - landed, arriving, leaves))

    _, stay_leg, return_departure = max(ground_times, key=lambda item: item[0])
    return str(stay_leg["destination"]).upper(), timezone.localtime(return_departure).date()


_MIN_ROUND_TRIP_LEGS = 2


def _parse_leg_time(raw: object) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, UTC)
    return parsed


class EnrichmentService:
    """Price one flight and record the answer."""

    def __init__(
        self,
        provider: PriceProvider | None = None,
        reviewer: FareReviewer | None = None,
        cache: QuoteCache | None = None,
    ) -> None:
        self._provider = provider or get_provider()
        self._reviewer = reviewer or get_reviewer()
        self._cache = cache or QuoteCache()

    def enrich(self, flight: Flight) -> EnrichmentOutcome:
        """Enrich one flight.

        Provider errors propagate: deciding whether a failure is worth
        retrying is the task's job, and it needs the exception type to make
        that call. The one exception is ``PriceUnavailable``, which is an
        answer ("no fare for this route"), not a failure.
        """
        outcome = EnrichmentOutcome(flight_id=flight.flight_id)
        query = build_query(flight)

        try:
            quote, outcome.cache_hit = self._cache.fetch_through(self._provider, query)
        except PriceUnavailable as exc:
            logger.info("No fare for %s: %s", flight.flight_id, exc)
            outcome.warnings.append(str(exc))
            self._persist(flight, outcome)
            return outcome

        outcome.quote = quote

        distance = flight.total_distance_miles
        if distance > 0:
            outcome.verdict = self._reviewer.review(query, quote, distance)
        else:
            outcome.warnings.append("Itinerary carried no leg distances, fare not reviewed.")

        self._persist(flight, outcome)
        return outcome

    @staticmethod
    @transaction.atomic
    def _persist(flight: Flight, outcome: EnrichmentOutcome) -> None:
        if outcome.quote is not None:
            flight.retail_price = outcome.quote.amount
            flight.currency = outcome.quote.currency
            flight.price_provider = outcome.quote.provider
        flight.fare_review = outcome.verdict.as_dict() if outcome.verdict else None
        flight.enriched = True
        flight.enriched_at = timezone.now()
        flight.save(
            update_fields=(
                "retail_price",
                "currency",
                "price_provider",
                "fare_review",
                "enriched",
                "enriched_at",
            )
        )
