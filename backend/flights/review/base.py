"""The port for fare plausibility review.

A quote is one number pulled out of a third-party answer. Nothing upstream
tells us whether that number makes sense for the itinerary -- a round-trip
fare returned for a one-way search, or a scraper that grabbed a basic-economy
teaser for a business cabin, both come back as a perfectly well-formed
Decimal. A reviewer is the cheap sanity check in front of that.
"""

from __future__ import annotations

import abc

from ..dto import FareVerdict, PriceQuery, PriceQuote


class FareReviewer(abc.ABC):
    """Judge whether a fetched fare is plausible for the itinerary."""

    name: str = ""

    @abc.abstractmethod
    def review(self, query: PriceQuery, quote: PriceQuote, distance_miles: int) -> FareVerdict:
        """Return a verdict. Must not raise -- a failed review is not a
        failed enrichment, so implementations degrade to
        ``FareVerdict.UNKNOWN`` instead of propagating."""
