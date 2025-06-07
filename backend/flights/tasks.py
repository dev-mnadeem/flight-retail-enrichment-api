"""Celery task: retry policy and status bookkeeping, nothing else.

The pipeline itself lives in ``flights.services.enrichment`` so it can be
exercised without a broker.
"""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task
from django.conf import settings

from .enums import TaskStatus
from .models import EnrichmentTask, Flight
from .providers import PermanentPricingError, TransientPricingError
from .services import EnrichmentService

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
#: Used when the provider gave no advice of its own.
DEFAULT_RETRY_DELAY_SECONDS = 30


@shared_task(bind=True, max_retries=MAX_RETRIES)
def enrich_flight_task(self, flight_id: str) -> dict[str, Any]:
    """Price one flight.

    Retries are deliberately *not* wired to ``autoretry_for=(Exception,)``.
    A missing flight row and a malformed provider response will fail the same
    way on every attempt, so retrying them just delays the failure by the
    length of the backoff ladder while holding a worker slot. Only
    ``TransientPricingError`` -- timeout, 5xx, rate limit -- earns a retry,
    and when the provider told us how long to wait we use its number.
    """
    task = _load_task(self.request.id)

    try:
        flight = Flight.objects.get(flight_id=flight_id)
    except Flight.DoesNotExist:
        message = f"Flight with id {flight_id} not found"
        logger.error(message)
        _fail(task, message)
        return {"flight_id": flight_id, "error": message}

    if task is not None:
        task.attempts = self.request.retries + 1
        task.mark(TaskStatus.STARTED)

    try:
        outcome = EnrichmentService().enrich(flight)
    except TransientPricingError as exc:
        delay = int(exc.retry_after or DEFAULT_RETRY_DELAY_SECONDS)
        if self.request.retries >= MAX_RETRIES:
            logger.error("Giving up on %s after %s attempts", flight_id, self.request.retries + 1)
            _fail(task, f"{exc} (gave up after {self.request.retries + 1} attempts)")
            raise
        logger.warning("Retrying %s in %ss: %s", flight_id, delay, exc)
        if task is not None:
            task.mark(TaskStatus.RETRYING, {"error": str(exc), "retry_in_seconds": delay})
        raise self.retry(exc=exc, countdown=delay) from exc
    except PermanentPricingError as exc:
        logger.error("Unrecoverable pricing error for %s: %s", flight_id, exc)
        _fail(task, str(exc))
        raise

    result = outcome.as_dict()
    if task is not None:
        task.mark(TaskStatus.SUCCESS, result)
    return result


def _load_task(task_id: str | None) -> EnrichmentTask | None:
    """Find the tracking row, tolerating its absence.

    A task invoked outside the API -- from a shell, a replay, a scheduled
    sweep -- has no row. That is not a reason to lose the enrichment, and it
    must not be a reason for the error handler itself to raise.
    """
    if not task_id:
        return None
    task = EnrichmentTask.objects.filter(task_id=task_id).first()
    if task is None:
        logger.info("No EnrichmentTask row for %s, running untracked", task_id)
    return task


def _fail(task: EnrichmentTask | None, message: str) -> None:
    if task is not None:
        task.mark(TaskStatus.FAILURE, {"error": message})


def enqueue(flight: Flight) -> EnrichmentTask:
    """Create the tracking row and queue the work for one flight.

    Callers get a row back whatever the broker does. With
    ``CELERY_TASK_ALWAYS_EAGER`` set -- the default when no broker URL is
    configured -- the task has already run by the time this returns.
    """
    import uuid

    task_id = str(uuid.uuid4())
    task = EnrichmentTask.objects.create(task_id=task_id, flight=flight, status=TaskStatus.PENDING)
    if settings.CELERY_TASK_ALWAYS_EAGER:
        enrich_flight_task.apply(args=[flight.flight_id], task_id=task_id)
    else:
        enrich_flight_task.apply_async(args=[flight.flight_id], task_id=task_id)
    task.refresh_from_db()
    return task
