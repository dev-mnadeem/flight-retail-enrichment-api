"""Fare-reviewer registry."""

from __future__ import annotations

from django.conf import settings

from .base import FareReviewer
from .claude import ClaudeFareReviewer
from .heuristic import HeuristicFareReviewer

__all__ = [
    "ClaudeFareReviewer",
    "FareReviewer",
    "HeuristicFareReviewer",
    "available_reviewers",
    "get_reviewer",
]

_BUILDERS = {
    HeuristicFareReviewer.name: HeuristicFareReviewer,
    ClaudeFareReviewer.name: ClaudeFareReviewer,
}


def available_reviewers() -> tuple[str, ...]:
    return tuple(sorted(_BUILDERS))


def get_reviewer(name: str | None = None) -> FareReviewer:
    key = (name or settings.FARE_REVIEWER).strip().lower()
    # An unknown reviewer name is a configuration typo, not a reason to fail
    # an enrichment -- fall back to the one that always works.
    return _BUILDERS.get(key, HeuristicFareReviewer)()
