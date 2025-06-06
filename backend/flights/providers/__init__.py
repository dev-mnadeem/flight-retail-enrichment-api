"""Price-provider registry.

Adding a source is two steps: implement ``PriceProvider`` and register the
class here. Nothing in the service layer, the task or the API changes.
"""

from __future__ import annotations

from django.conf import settings

from .base import (
    PermanentPricingError,
    PriceProvider,
    PriceUnavailable,
    PricingError,
    TransientPricingError,
)
from .fixture import FixturePriceProvider
from .serpapi import SerpApiPriceProvider

__all__ = [
    "FixturePriceProvider",
    "PermanentPricingError",
    "PriceProvider",
    "PriceUnavailable",
    "PricingError",
    "SerpApiPriceProvider",
    "TransientPricingError",
    "available_providers",
    "get_provider",
]

_BUILDERS = {
    FixturePriceProvider.name: lambda: FixturePriceProvider(),
    SerpApiPriceProvider.name: lambda: SerpApiPriceProvider(api_key=settings.SERPAPI_KEY),
}


def available_providers() -> tuple[str, ...]:
    return tuple(sorted(_BUILDERS))


def get_provider(name: str | None = None) -> PriceProvider:
    key = (name or settings.FLIGHT_PRICE_PROVIDER).strip().lower()
    try:
        build = _BUILDERS[key]
    except KeyError:
        raise PermanentPricingError(
            f"Unknown price provider {key!r}. Known providers: {', '.join(available_providers())}"
        ) from None
    return build()
