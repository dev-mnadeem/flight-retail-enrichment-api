"""SerpAPI Google Flights adapter.

Kept deliberately thin: build params, call, translate errors, parse one
number. Everything about *when* to call and what to do with the answer lives
in the service layer.
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from ..dto import PriceQuery, PriceQuote
from .base import (
    PermanentPricingError,
    PriceProvider,
    PriceUnavailable,
    TransientPricingError,
)

logger = logging.getLogger(__name__)

SEARCH_URL = "https://serpapi.com/search.json"

#: Connect/read budget for one search. The endpoint answers in seconds; a
#: minutes-long ceiling only means a stuck call pins a worker slot.
REQUEST_TIMEOUT_SECONDS = 15.0

#: Default pause when we are rate limited and the response carries no
#: Retry-After header of its own.
DEFAULT_RATE_LIMIT_BACKOFF_SECONDS = 30.0

_TOO_MANY_REQUESTS = 429
_SERVER_ERROR_FLOOR = 500

#: Answer keys in preference order. "best_flights" is Google's own ranking;
#: "other_flights" is the long tail and is only consulted when the ranked
#: list is empty, which happens on thin routes.
_RESULT_KEYS = ("best_flights", "other_flights")


class SerpApiPriceProvider(PriceProvider):
    name = "serpapi"

    def __init__(self, api_key: str, client: httpx.Client | None = None) -> None:
        if not api_key:
            raise PermanentPricingError(
                "SERPAPI_KEY is empty. Set it, or run with FLIGHT_PRICE_PROVIDER=fixture."
            )
        self._api_key = api_key
        self._client = client

    def fetch(self, query: PriceQuery) -> PriceQuote:
        params = self._build_params(query)
        try:
            data = self._get(params)
        except httpx.TimeoutException as exc:
            raise TransientPricingError(f"SerpAPI timed out: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            raise self._classify_status(exc) from exc
        except httpx.HTTPError as exc:
            raise TransientPricingError(f"SerpAPI transport error: {exc}") from exc

        if error := data.get("error"):
            # SerpAPI reports quota and key problems with HTTP 200 and an
            # "error" string, so the status code alone is not enough.
            raise PermanentPricingError(f"SerpAPI rejected the search: {error}")

        return self._parse(data, query)

    def _build_params(self, query: PriceQuery) -> dict[str, Any]:
        params: dict[str, Any] = {
            "engine": "google_flights",
            "departure_id": query.origin,
            "arrival_id": query.destination,
            "outbound_date": query.outbound_date.isoformat(),
            "type": query.trip_type.serpapi_code,
            "travel_class": query.cabin.serpapi_code,
            "currency": query.currency,
            "hl": "en",
            "api_key": self._api_key,
        }
        if query.return_date is not None:
            params["return_date"] = query.return_date.isoformat()
        return params

    def _get(self, params: dict[str, Any]) -> dict[str, Any]:
        if self._client is not None:
            response = self._client.get(SEARCH_URL, params=params)
            response.raise_for_status()
            return response.json()
        with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = client.get(SEARCH_URL, params=params)
            response.raise_for_status()
            return response.json()

    @staticmethod
    def _classify_status(exc: httpx.HTTPStatusError) -> Exception:
        status = exc.response.status_code
        if status == _TOO_MANY_REQUESTS:
            return TransientPricingError(
                "SerpAPI rate limit reached",
                retry_after=_retry_after(exc.response),
            )
        if status >= _SERVER_ERROR_FLOOR:
            return TransientPricingError(f"SerpAPI returned {status}")
        return PermanentPricingError(f"SerpAPI returned {status}: {exc.response.text[:200]}")

    def _parse(self, data: dict[str, Any], query: PriceQuery) -> PriceQuote:
        entry = _first_priced_entry(data)
        if entry is None:
            raise PriceUnavailable(
                f"SerpAPI returned no priced itinerary for "
                f"{query.origin}-{query.destination} on {query.outbound_date}"
            )

        raw_price = entry["price"]
        try:
            amount = Decimal(str(raw_price))
        except (InvalidOperation, TypeError) as exc:
            raise PermanentPricingError(f"SerpAPI price was not a number: {raw_price!r}") from exc

        # The engine echoes back the currency it actually used. Trusting our
        # own request parameter instead is how a EUR fare gets stored as USD.
        currency = (data.get("search_parameters") or {}).get("currency") or query.currency
        return PriceQuote(
            amount=amount,
            currency=currency,
            provider=self.name,
            source_label=_airline_label(entry),
        )


def _first_priced_entry(data: dict[str, Any]) -> dict[str, Any] | None:
    """Find the first itinerary that actually carries a price.

    A partial upstream answer -- the key present but the list empty, or the
    entries present with the price field missing -- is common enough that
    indexing ``[0]`` blindly is a real crash, not a theoretical one.
    """
    for key in _RESULT_KEYS:
        for entry in data.get(key) or []:
            if isinstance(entry, dict) and entry.get("price") is not None:
                return entry
    return None


def _airline_label(entry: dict[str, Any]) -> str:
    legs = entry.get("flights") or []
    airlines = [leg.get("airline") for leg in legs if isinstance(leg, dict) and leg.get("airline")]
    return " / ".join(dict.fromkeys(airlines))


def _retry_after(response: httpx.Response) -> float:
    raw = response.headers.get("Retry-After")
    if raw is None:
        return DEFAULT_RATE_LIMIT_BACKOFF_SECONDS
    try:
        return float(raw)
    except ValueError:
        # The header also allows an HTTP date. We do not need that precision
        # for a backoff, so fall back to the default rather than parse it.
        logger.debug("Unparsed Retry-After header: %s", raw)
        return DEFAULT_RATE_LIMIT_BACKOFF_SECONDS
