"""Typed values that cross the layer boundaries.

Keeping these separate from the Django models means the provider package can
be unit-tested without a database, and a provider never has to know how a
``Flight`` row is shaped.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from .enums import CabinClass, TripType


@dataclass(frozen=True, slots=True)
class PriceQuery:
    """Everything a provider needs to price one itinerary."""

    origin: str
    destination: str
    outbound_date: date
    cabin: CabinClass
    trip_type: TripType
    currency: str = "USD"
    return_date: date | None = None

    def __post_init__(self) -> None:
        if self.trip_type is TripType.ROUND_TRIP and self.return_date is None:
            raise ValueError("A round-trip query needs a return_date")
        if self.trip_type is TripType.ONE_WAY and self.return_date is not None:
            raise ValueError("A one-way query must not carry a return_date")

    @property
    def cache_key(self) -> str:
        """Stable fingerprint of the query, used as the quote-cache key.

        Sorted keys and ISO dates keep the digest reproducible across
        processes, which is the whole point -- two workers pricing the same
        itinerary must land on the same key or the cache never hits.
        """
        payload = json.dumps(
            {
                "origin": self.origin,
                "destination": self.destination,
                "outbound_date": self.outbound_date.isoformat(),
                "return_date": self.return_date.isoformat() if self.return_date else None,
                "cabin": self.cabin.value,
                "trip_type": self.trip_type.value,
                "currency": self.currency,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class PriceQuote:
    """A price with the currency it was actually quoted in.

    The currency is not decoration. The provider is told which currency to
    quote in, but it is free to ignore that, and a bare number stored without
    its unit is the classic way an enrichment pipeline ends up comparing
    dollars with euros.
    """

    amount: Decimal
    currency: str
    provider: str
    source_label: str = ""

    def __post_init__(self) -> None:
        if self.amount < 0:
            raise ValueError("A fare cannot be negative")
        if len(self.currency) != _CURRENCY_CODE_LENGTH:
            raise ValueError(f"Expected an ISO 4217 currency code, got {self.currency!r}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "amount": str(self.amount),
            "currency": self.currency,
            "provider": self.provider,
            "source_label": self.source_label,
        }


_CURRENCY_CODE_LENGTH = 3


@dataclass(frozen=True, slots=True)
class FareVerdict:
    """The optional plausibility review attached to a quote."""

    rating: str
    rationale: str
    reviewer: str
    cents_per_mile: float | None = None

    PLAUSIBLE = "plausible"
    LOW = "suspiciously_low"
    HIGH = "suspiciously_high"
    UNKNOWN = "unknown"

    def as_dict(self) -> dict[str, Any]:
        return {
            "rating": self.rating,
            "rationale": self.rationale,
            "reviewer": self.reviewer,
            "cents_per_mile": self.cents_per_mile,
        }


@dataclass(slots=True)
class EnrichmentOutcome:
    """What the service layer hands back to the Celery task."""

    flight_id: str
    quote: PriceQuote | None = None
    verdict: FareVerdict | None = None
    cache_hit: bool = False
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "flight_id": self.flight_id,
            "retail_price": str(self.quote.amount) if self.quote else None,
            "currency": self.quote.currency if self.quote else None,
            "provider": self.quote.provider if self.quote else None,
            "cache_hit": self.cache_hit,
            "review": self.verdict.as_dict() if self.verdict else None,
            "warnings": list(self.warnings),
        }
