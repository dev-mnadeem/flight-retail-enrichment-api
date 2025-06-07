"""Submit itineraries for enrichment and read back task status."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status
from flights.models import EnrichmentTask
from flights.tasks import enqueue

from api.schemas import (
    BatchAccepted,
    BatchItemResult,
    FlightBatch,
    FlightData,
    TaskAccepted,
    TaskStatusResponse,
)
from api.services import save_flight

logger = logging.getLogger(__name__)
router = APIRouter(tags=["enrichment"])


@router.post("/enrich-flight", response_model=TaskAccepted, status_code=status.HTTP_202_ACCEPTED)
def enrich_flight(payload: FlightData) -> TaskAccepted:
    """Store one itinerary and queue it for pricing."""
    flight = save_flight(payload)
    task = enqueue(flight)
    return TaskAccepted(task_id=task.task_id, flight_id=flight.flight_id, status=task.status)


@router.post("/enrich-flights", response_model=BatchAccepted, status_code=status.HTTP_202_ACCEPTED)
def enrich_flights(payload: FlightBatch) -> BatchAccepted:
    """Store and queue a batch of itineraries.

    Each entry is isolated. An upstream feed that ships one bad record should
    not cost the caller the other forty-nine, so a failure is reported
    against its own flight id and the loop carries on.
    """
    results: list[BatchItemResult] = []
    for item in payload.flights:
        try:
            flight = save_flight(item)
            task = enqueue(flight)
        except Exception as exc:
            logger.exception("Could not queue %s", item.id)
            results.append(BatchItemResult(flight_id=item.id, accepted=False, error=str(exc)))
            continue
        results.append(
            BatchItemResult(
                flight_id=flight.flight_id,
                accepted=True,
                task_id=task.task_id,
                status=task.status,
            )
        )

    accepted = sum(1 for item in results if item.accepted)
    return BatchAccepted(
        submitted=len(results),
        accepted=accepted,
        rejected=len(results) - accepted,
        results=results,
    )


@router.get("/task-status/{task_id}", response_model=TaskStatusResponse)
def get_task_status(task_id: str) -> TaskStatusResponse:
    """Status of one enrichment task, with the abridged flight it covers."""
    task = EnrichmentTask.objects.with_flight().filter(task_id=task_id).first()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    return TaskStatusResponse(
        task_id=task.task_id,
        status=task.status,
        attempts=task.attempts,
        created_at=task.created_at,
        completed_at=task.completed_at,
        flight=task.flight.summary(),
        result=task.result,
    )
