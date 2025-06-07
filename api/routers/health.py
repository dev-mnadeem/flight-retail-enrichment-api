"""Liveness and configuration readout."""

from __future__ import annotations

from django.conf import settings
from django.db import connection
from fastapi import APIRouter

from api.schemas import HealthResponse

router = APIRouter(tags=["ops"])


@router.get("/healthz", response_model=HealthResponse)
def healthz() -> HealthResponse:
    """Report which provider and reviewer this process is actually wired to.

    Which adapter is live is the single most common source of confusion when
    the answers look wrong, so it is worth an endpoint.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        database = "ok"
    except Exception as exc:  # pragma: no cover - only on a broken database
        database = f"error: {exc}"

    return HealthResponse(
        status="ok" if database == "ok" else "degraded",
        database=database,
        price_provider=settings.FLIGHT_PRICE_PROVIDER,
        fare_reviewer=settings.FARE_REVIEWER,
        celery_eager=settings.CELERY_TASK_ALWAYS_EAGER,
    )
