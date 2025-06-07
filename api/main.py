"""FastAPI application.

Django is booted first, then the routers are imported -- every router pulls
in a model, and a model import before ``django.setup()`` raises
``AppRegistryNotReady``.
"""

from __future__ import annotations

from api.bootstrap import setup_django

setup_django()

from fastapi import FastAPI  # noqa: E402
from fastapi.responses import RedirectResponse  # noqa: E402

from api.routers import enrichment, flights, health  # noqa: E402

DESCRIPTION = """
Submit a flight itinerary, get a task id back, and poll it for a retail fare.

Pricing goes through a provider interface. The default provider serves
deterministic fares from a checked-in fixture, so the service runs with no
API key. Set `FLIGHT_PRICE_PROVIDER=serpapi` plus `SERPAPI_KEY` to price
against Google Flights instead.
"""

app = FastAPI(
    title="Flight data enrichment",
    description=DESCRIPTION,
    version="1.0.0",
)

app.include_router(health.router)
app.include_router(enrichment.router)
app.include_router(flights.router)


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/docs")
