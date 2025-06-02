"""Reviewer backed by the Anthropic Messages API.

The model sees the itinerary shape as well as the number -- leg count,
layover, cabin, distance, currency -- which is the part a fixed band table
cannot weigh. It is opt-in (``FARE_REVIEWER=claude``) and it degrades to the
heuristic on every failure path, including "no credentials configured", so
the pipeline never depends on it being reachable.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from django.conf import settings

from ..dto import FareVerdict, PriceQuery, PriceQuote
from .base import FareReviewer
from .heuristic import HeuristicFareReviewer

logger = logging.getLogger(__name__)

MODEL = "claude-opus-5"
MAX_TOKENS = 1024

SYSTEM_PROMPT = (
    "You review airline fares for an enrichment pipeline. Given an itinerary "
    "and a fetched price, decide whether the price is plausible for that "
    "cabin and distance, or whether it looks like the wrong fare was picked "
    "up. Always answer by calling the record_verdict tool."
)

#: A tool schema is how we get a fixed shape back instead of prose we would
#: then have to parse out of a paragraph.
VERDICT_TOOL: dict[str, Any] = {
    "name": "record_verdict",
    "description": "Record the plausibility verdict for one fetched fare.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "rating": {
                "type": "string",
                "enum": [FareVerdict.PLAUSIBLE, FareVerdict.LOW, FareVerdict.HIGH],
            },
            "rationale": {
                "type": "string",
                "description": "One sentence, under 200 characters.",
            },
        },
        "required": ["rating", "rationale"],
        "additionalProperties": False,
    },
}


class ClaudeFareReviewer(FareReviewer):
    name = "claude"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key if api_key is not None else settings.ANTHROPIC_API_KEY
        self._fallback = HeuristicFareReviewer()
        self._client: Any | None = None

    def review(self, query: PriceQuery, quote: PriceQuote, distance_miles: int) -> FareVerdict:
        client = self._get_client()
        if client is None:
            return self._fallback.review(query, quote, distance_miles)
        try:
            return self._ask(client, query, quote, distance_miles)
        except Exception:
            # A review is advisory. Losing it must never cost us the price we
            # already paid a provider to fetch.
            logger.warning("Claude fare review failed, using the heuristic", exc_info=True)
            return self._fallback.review(query, quote, distance_miles)

    def _get_client(self) -> Any | None:
        if self._client is not None:
            return self._client
        if not self._api_key:
            logger.info("ANTHROPIC_API_KEY is unset, using the heuristic reviewer")
            return None
        try:
            import anthropic
        except ImportError:
            logger.info("The anthropic package is not installed, using the heuristic reviewer")
            return None
        self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client

    def _ask(
        self,
        client: Any,
        query: PriceQuery,
        quote: PriceQuote,
        distance_miles: int,
    ) -> FareVerdict:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=[VERDICT_TOOL],
            messages=[{"role": "user", "content": _build_prompt(query, quote, distance_miles)}],
        )
        for block in response.content:
            if block.type == "tool_use" and block.name == VERDICT_TOOL["name"]:
                payload = block.input
                if isinstance(payload, str):
                    payload = json.loads(payload)
                return FareVerdict(
                    rating=payload["rating"],
                    rationale=payload["rationale"],
                    reviewer=self.name,
                    cents_per_mile=_safe_rate(quote, distance_miles),
                )
        raise ValueError("Claude returned no record_verdict tool call")


def _build_prompt(query: PriceQuery, quote: PriceQuote, distance_miles: int) -> str:
    return (
        f"Route: {query.origin} to {query.destination}\n"
        f"Cabin: {query.cabin.value}\n"
        f"Trip type: {query.trip_type.value}\n"
        f"Outbound: {query.outbound_date.isoformat()}\n"
        f"Great-circle distance: {distance_miles} miles\n"
        f"Fetched fare: {quote.amount} {quote.currency} from {quote.provider}\n"
        "Is this fare plausible for that cabin and distance?"
    )


def _safe_rate(quote: PriceQuote, distance_miles: int) -> float | None:
    from .heuristic import cents_per_mile

    if distance_miles <= 0:
        return None
    return round(cents_per_mile(quote.amount, distance_miles), 2)
