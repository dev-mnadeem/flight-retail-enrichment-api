"""Database schema.

Three tables: the itinerary we were asked about, the enrichment request we
raised for it, and the provider quotes we have already paid for.
"""

from __future__ import annotations

from datetime import timedelta

from django.db import models
from django.utils import timezone

from .enums import CabinClass, TaskStatus

#: Widest ``flight_id`` an upstream feed is allowed to send.
FLIGHT_ID_MAX_LENGTH = 100
#: IATA codes are 3 letters, ICAO 4. 8 leaves room for a rail or bus code.
LOCATION_CODE_MAX_LENGTH = 8
#: Celery task ids are UUID4 strings, but we do not want to reject a broker
#: that hands out something longer.
TASK_ID_MAX_LENGTH = 255
CURRENCY_CODE_LENGTH = 3
PRICE_MAX_DIGITS = 10
PRICE_DECIMAL_PLACES = 2


class Flight(models.Model):
    """One itinerary, as submitted, plus whatever we enriched it with."""

    flight_id = models.CharField(max_length=FLIGHT_ID_MAX_LENGTH, unique=True)
    travel_class = models.CharField(
        max_length=32, choices=CabinClass.choices, default=CabinClass.ECONOMY
    )
    origin = models.CharField(max_length=LOCATION_CODE_MAX_LENGTH)
    destination = models.CharField(max_length=LOCATION_CODE_MAX_LENGTH)
    departure_time = models.DateTimeField()
    arrival_time = models.DateTimeField()
    flight_numbers = models.JSONField(default=list)
    legs = models.JSONField(default=list)
    last_seen = models.DateTimeField()

    retail_price = models.DecimalField(
        max_digits=PRICE_MAX_DIGITS,
        decimal_places=PRICE_DECIMAL_PLACES,
        null=True,
        blank=True,
    )
    # A price without its currency is not a price. Stored alongside rather
    # than assumed, because the provider decides what it quotes in.
    currency = models.CharField(max_length=CURRENCY_CODE_LENGTH, blank=True, default="")
    price_provider = models.CharField(max_length=32, blank=True, default="")
    enriched = models.BooleanField(default=False)
    enriched_at = models.DateTimeField(null=True, blank=True)
    fare_review = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ("-last_seen", "flight_id")
        indexes = [
            # The flight list filters on these; the task list does not touch
            # this table at all.
            models.Index(fields=("enriched", "-last_seen"), name="flight_enriched_seen_idx"),
            models.Index(fields=("origin", "destination"), name="flight_route_idx"),
        ]

    def __str__(self) -> str:
        return self.flight_id

    @property
    def cabin(self) -> CabinClass:
        return CabinClass.parse(self.travel_class)

    @property
    def total_distance_miles(self) -> int:
        """Sum of the submitted per-leg distances.

        Zero when the payload carried no distances, which the reviewer treats
        as "not scorable" rather than as a zero-mile flight.
        """
        total = 0
        for leg in self.legs or []:
            if isinstance(leg, dict):
                try:
                    total += int(leg.get("distance") or 0)
                except (TypeError, ValueError):
                    continue
        return total

    def summary(self) -> dict[str, object]:
        """Abridged flight info, as the task-status response returns it."""
        return {
            "id": self.flight_id,
            "origin": self.origin,
            "destination": self.destination,
            "travel_class": self.travel_class,
            "departure_time": self.departure_time.isoformat(),
            "arrival_time": self.arrival_time.isoformat(),
            "flight_numbers": self.flight_numbers,
            "leg_count": len(self.legs or []),
        }


class EnrichmentTaskQuerySet(models.QuerySet):
    def completed(self) -> EnrichmentTaskQuerySet:
        return self.filter(status__in=TaskStatus.terminal())

    def with_flight(self) -> EnrichmentTaskQuerySet:
        """Join the flight row.

        The task list renders ``task.flight.flight_id`` for every row, which
        is one query per task without this.
        """
        return self.select_related("flight")


class EnrichmentTask(models.Model):
    """One enrichment request against one flight."""

    task_id = models.CharField(max_length=TASK_ID_MAX_LENGTH, unique=True)
    flight = models.ForeignKey(Flight, on_delete=models.CASCADE, related_name="tasks")
    status = models.CharField(max_length=16, choices=TaskStatus.choices, default=TaskStatus.PENDING)
    result = models.JSONField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    objects = EnrichmentTaskQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            # The task list is "completed tasks, newest first" -- exactly
            # this composite.
            models.Index(fields=("status", "-completed_at"), name="task_status_completed_idx"),
            models.Index(fields=("flight", "-created_at"), name="task_flight_created_idx"),
        ]

    def __str__(self) -> str:
        return f"Task {self.task_id} - {self.status}"

    def mark(self, status: str, result: dict | None = None) -> None:
        self.status = status
        if result is not None:
            self.result = result
        if status in TaskStatus.terminal():
            self.completed_at = timezone.now()
        self.save(update_fields=("status", "result", "completed_at", "attempts"))


class PriceQuoteCache(models.Model):
    """Quotes we have already fetched, keyed by the query fingerprint.

    Without this, resubmitting the same itinerary buys the same answer from
    the provider again. SerpAPI is metered per search, so a duplicate
    submission is a duplicate charge, not just a duplicate wait.
    """

    query_hash = models.CharField(max_length=64, primary_key=True)
    origin = models.CharField(max_length=LOCATION_CODE_MAX_LENGTH)
    destination = models.CharField(max_length=LOCATION_CODE_MAX_LENGTH)
    cabin = models.CharField(max_length=32)
    amount = models.DecimalField(max_digits=PRICE_MAX_DIGITS, decimal_places=PRICE_DECIMAL_PLACES)
    currency = models.CharField(max_length=CURRENCY_CODE_LENGTH)
    provider = models.CharField(max_length=32)
    source_label = models.CharField(max_length=255, blank=True, default="")
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=("-fetched_at",), name="quote_fetched_idx")]

    def __str__(self) -> str:
        return f"{self.origin}-{self.destination} {self.cabin}: {self.amount} {self.currency}"

    def is_fresh(self, ttl_seconds: int) -> bool:
        return timezone.now() - self.fetched_at < timedelta(seconds=ttl_seconds)
