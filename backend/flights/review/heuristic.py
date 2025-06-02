"""Deterministic reviewer: cents per mile against published fare bands.

This is the default, and it is the fallback for every other reviewer. It
needs no network, no key and no model, and it catches the failure that
actually shows up in practice: a fare that is off by a multiple, not one that
is off by ten percent.
"""

from __future__ import annotations

from decimal import Decimal

from ..dto import FareVerdict, PriceQuery, PriceQuote
from .base import FareReviewer

#: Plausible cents-per-mile bands by cabin, as (low, high).
#: Wide on purpose -- the job is to flag an order-of-magnitude mistake, and a
#: narrow band would spend all its time crying wolf about a good sale fare.
CENTS_PER_MILE_BANDS = {
    "Economy": (2.0, 45.0),
    "Premium Economy": (5.0, 90.0),
    "Business": (12.0, 240.0),
    "First": (20.0, 450.0),
}

#: Short hops carry a fixed cost that swamps the per-mile figure, so the
#: band check is not applied below this distance.
MIN_SCORABLE_DISTANCE_MILES = 250

_CENTS_PER_DOLLAR = Decimal("100")


def cents_per_mile(amount: Decimal, distance_miles: int) -> float:
    if distance_miles <= 0:
        raise ValueError("distance_miles must be positive")
    return float(amount * _CENTS_PER_DOLLAR / Decimal(distance_miles))


class HeuristicFareReviewer(FareReviewer):
    name = "heuristic"

    def review(self, query: PriceQuery, quote: PriceQuote, distance_miles: int) -> FareVerdict:
        if distance_miles < MIN_SCORABLE_DISTANCE_MILES:
            return FareVerdict(
                rating=FareVerdict.UNKNOWN,
                rationale=(
                    f"Itinerary is {distance_miles} mi, below the "
                    f"{MIN_SCORABLE_DISTANCE_MILES} mi floor where a per-mile "
                    "fare band is meaningful."
                ),
                reviewer=self.name,
            )

        rate = cents_per_mile(quote.amount, distance_miles)
        low, high = CENTS_PER_MILE_BANDS[query.cabin.value]

        if rate < low:
            rating = FareVerdict.LOW
            rationale = (
                f"{rate:.1f} c/mi is below the {low:.0f}-{high:.0f} c/mi band for "
                f"{query.cabin.value}, which usually means the fare belongs to a "
                "cheaper cabin than the one requested."
            )
        elif rate > high:
            rating = FareVerdict.HIGH
            rationale = (
                f"{rate:.1f} c/mi is above the {low:.0f}-{high:.0f} c/mi band for "
                f"{query.cabin.value}, which usually means a round-trip or "
                "multi-passenger total was read as a single one-way fare."
            )
        else:
            rating = FareVerdict.PLAUSIBLE
            rationale = (
                f"{rate:.1f} c/mi sits inside the {low:.0f}-{high:.0f} c/mi band for "
                f"{query.cabin.value}."
            )

        return FareVerdict(
            rating=rating,
            rationale=rationale,
            reviewer=self.name,
            cents_per_mile=round(rate, 2),
        )
