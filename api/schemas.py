"""Request and response bodies for the HTTP layer.

These are the wire contract. They are deliberately separate from the Django
models: the payload shape is fixed by whoever is sending it, and the schema
is free to evolve without a migration.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

MAX_BATCH_SIZE = 50


def _require_aware(value: datetime) -> datetime:
    """Treat a naive timestamp as UTC.

    The sample payload mixes ``2025-06-13T12:55:00`` with
    ``2025-05-29T03:38:05Z``. Normalising here means nothing downstream has
    to guess, and no naive datetime ever reaches a ``USE_TZ=True`` database.
    """

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class FlightLeg(BaseModel):
    origin: str = Field(min_length=1, max_length=8)
    destination: str = Field(min_length=1, max_length=8)
    departure_time: datetime
    arrival_time: datetime
    flight_number: str
    aircraft_type: str = ""
    cabin_type: str = ""
    duration: int = Field(ge=0, default=0)
    # The exercise payload sends these as strings ("235.0"), so coercion is
    # part of the contract rather than a convenience.
    layover_time: float = Field(ge=0, default=0.0)
    distance: int = Field(ge=0, default=0)

    _aware = field_validator("departure_time", "arrival_time")(_require_aware)


class FlightData(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    travel_class: str
    origin: str = Field(min_length=1, max_length=8)
    destination: str = Field(min_length=1, max_length=8)
    departure_time: datetime
    arrival_time: datetime
    flight_numbers: list[str] = Field(default_factory=list)
    legs: list[FlightLeg] = Field(default_factory=list)
    last_seen: datetime

    _aware = field_validator("departure_time", "arrival_time", "last_seen")(_require_aware)

    @field_validator("origin", "destination")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.strip().upper()


class FlightBatch(BaseModel):
    flights: list[FlightData] = Field(min_length=1, max_length=MAX_BATCH_SIZE)


class TaskAccepted(BaseModel):
    task_id: str
    flight_id: str
    status: str


class BatchItemResult(BaseModel):
    """One entry of a batch response.

    Carries either a task or an error, never both. A batch where the third
    itinerary is malformed still enqueues the other forty-nine.
    """

    flight_id: str
    accepted: bool
    task_id: str | None = None
    status: str | None = None
    error: str | None = None


class BatchAccepted(BaseModel):
    submitted: int
    accepted: int
    rejected: int
    results: list[BatchItemResult]


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    attempts: int
    created_at: datetime
    completed_at: datetime | None = None
    flight: dict[str, Any] | None = None
    result: dict[str, Any] | None = None


class FlightSummary(BaseModel):
    id: str
    origin: str
    destination: str
    travel_class: str
    departure_time: datetime
    arrival_time: datetime
    retail_price: str | None = None
    currency: str | None = None
    price_provider: str | None = None
    enriched: bool = False
    fare_review: dict[str, Any] | None = None


class FlightPage(BaseModel):
    items: list[FlightSummary]
    total: int
    limit: int
    offset: int


class HealthResponse(BaseModel):
    status: str
    database: str
    price_provider: str
    fare_reviewer: str
    celery_eager: bool
