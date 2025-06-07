"""Read-through cache in front of the price providers."""

from __future__ import annotations

import logging
from decimal import Decimal

from django.conf import settings

from ..dto import PriceQuery, PriceQuote
from ..models import PriceQuoteCache
from ..providers import PriceProvider

logger = logging.getLogger(__name__)


class QuoteCache:
    """Serve a fare from the database when one is still fresh.

    The unit being saved is a metered provider search, not a millisecond, so
    the TTL is measured in hours rather than seconds. Fares do move, which is
    why this expires at all instead of being a permanent lookup table.
    """

    def __init__(self, ttl_seconds: int | None = None) -> None:
        self.ttl_seconds = (
            ttl_seconds if ttl_seconds is not None else settings.PRICE_QUOTE_TTL_SECONDS
        )

    def get(self, query: PriceQuery) -> PriceQuote | None:
        row = PriceQuoteCache.objects.filter(query_hash=query.cache_key).first()
        if row is None:
            return None
        if not row.is_fresh(self.ttl_seconds):
            logger.debug("Quote for %s expired", query.cache_key[:12])
            return None
        return PriceQuote(
            amount=Decimal(row.amount),
            currency=row.currency,
            provider=row.provider,
            source_label=row.source_label,
        )

    def put(self, query: PriceQuery, quote: PriceQuote) -> None:
        PriceQuoteCache.objects.update_or_create(
            query_hash=query.cache_key,
            defaults={
                "origin": query.origin,
                "destination": query.destination,
                "cabin": query.cabin.value,
                "amount": quote.amount,
                "currency": quote.currency,
                "provider": quote.provider,
                "source_label": quote.source_label,
            },
        )

    def fetch_through(self, provider: PriceProvider, query: PriceQuery) -> tuple[PriceQuote, bool]:
        """Return ``(quote, cache_hit)``, calling the provider only on a miss."""
        cached = self.get(query)
        if cached is not None:
            return cached, True
        quote = provider.fetch(query)
        self.put(query, quote)
        return quote, False
