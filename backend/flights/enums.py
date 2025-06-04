"""Vocabulary shared by the API, the Celery task and the Django views."""

from django.db import models


class TaskStatus(models.TextChoices):
    """Lifecycle of a single enrichment request.

    Mirrors the Celery states we care about. ``RETRYING`` is ours: Celery
    reports a retrying task as PENDING, which is indistinguishable from
    "never started" and is the state a caller most wants to tell apart.
    """

    PENDING = "PENDING", "Pending"
    STARTED = "STARTED", "Started"
    RETRYING = "RETRYING", "Retrying"
    SUCCESS = "SUCCESS", "Success"
    FAILURE = "FAILURE", "Failure"

    @classmethod
    def terminal(cls) -> tuple[str, ...]:
        return (cls.SUCCESS.value, cls.FAILURE.value)


class CabinClass(models.TextChoices):
    """Cabin classes we can price.

    ``serpapi_code`` is the integer the Google Flights engine expects for its
    ``travel_class`` parameter: 1 economy, 2 premium economy, 3 business,
    4 first. Sending no value at all defaults the search to economy, which
    silently prices a business itinerary at the wrong fare.
    """

    ECONOMY = "Economy", "Economy"
    PREMIUM_ECONOMY = "Premium Economy", "Premium economy"
    BUSINESS = "Business", "Business"
    FIRST = "First", "First"

    @property
    def serpapi_code(self) -> int:
        return _SERPAPI_TRAVEL_CLASS[self]

    @classmethod
    def parse(cls, raw: str) -> "CabinClass":
        """Best-effort mapping of free-text cabin names onto the enum.

        Upstream feeds spell these inconsistently ("BUSINESS", "premium
        economy", "Biz"). Anything unrecognised falls back to economy, which
        is the conservative choice: it never over-states the fare band.
        """
        normalised = " ".join(raw.split()).casefold()
        return _CABIN_ALIASES.get(normalised, cls.ECONOMY)


_SERPAPI_TRAVEL_CLASS = {
    CabinClass.ECONOMY: 1,
    CabinClass.PREMIUM_ECONOMY: 2,
    CabinClass.BUSINESS: 3,
    CabinClass.FIRST: 4,
}

_CABIN_ALIASES = {
    "economy": CabinClass.ECONOMY,
    "coach": CabinClass.ECONOMY,
    "eco": CabinClass.ECONOMY,
    "premium economy": CabinClass.PREMIUM_ECONOMY,
    "premium": CabinClass.PREMIUM_ECONOMY,
    "premium_economy": CabinClass.PREMIUM_ECONOMY,
    "business": CabinClass.BUSINESS,
    "biz": CabinClass.BUSINESS,
    "first": CabinClass.FIRST,
    "first class": CabinClass.FIRST,
}


class TripType(models.TextChoices):
    """Round trip vs one way.

    The Google Flights engine encodes this as 1 (round trip) or 2 (one way).
    A multi-leg itinerary that ends somewhere other than where it started is
    one way -- pricing it as a round trip returns a fare for a journey the
    passenger is not taking.
    """

    ROUND_TRIP = "round_trip", "Round trip"
    ONE_WAY = "one_way", "One way"

    @property
    def serpapi_code(self) -> int:
        return 1 if self is TripType.ROUND_TRIP else 2
