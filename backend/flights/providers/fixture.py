"""Offline provider: prices come from a checked-in JSON file.

This is the default so that ``git clone && pytest`` works with no API key, no
network and no account. It is also how the enrichment tests assert on exact
numbers -- a live provider cannot be pinned to a value.
"""

from __future__ import annotations

import json
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..dto import PriceQuery, PriceQuote
from .base import PriceProvider, PriceUnavailable

FIXTURE_PATH = Path(__file__).resolve().parent / "data" / "fares.json"

#: Applied to the economy base fare when the route has no explicit entry for
#: the requested cabin. Roughly the shape of published long-haul fare ladders.
CABIN_MULTIPLIERS = {
    "Economy": Decimal("1.00"),
    "Premium Economy": Decimal("1.90"),
    "Business": Decimal("4.20"),
    "First": Decimal("7.50"),
}

#: A return leg is priced as a discount on two one-way fares, not as double.
ROUND_TRIP_MULTIPLIER = Decimal("1.80")

_CENTS = Decimal("0.01")


@lru_cache(maxsize=1)
def _load_fares() -> dict[str, Any]:
    with FIXTURE_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


class FixturePriceProvider(PriceProvider):
    name = "fixture"

    def fetch(self, query: PriceQuery) -> PriceQuote:
        fares = _load_fares()
        route_key = f"{query.origin.upper()}-{query.destination.upper()}"
        route = fares["routes"].get(route_key)
        if route is None:
            raise PriceUnavailable(f"No fixture fare for route {route_key}")

        base = Decimal(str(route["economy_base"]))
        amount = base * CABIN_MULTIPLIERS[query.cabin.value]
        if query.return_date is not None:
            amount *= ROUND_TRIP_MULTIPLIER

        return PriceQuote(
            amount=amount.quantize(_CENTS),
            currency=route.get("currency", fares["default_currency"]),
            provider=self.name,
            source_label=route.get("label", route_key),
        )
