"""Server-rendered views: the task queue and the flight table."""

from __future__ import annotations

from typing import Any

from django.views.generic import ListView

from .enums import CabinClass
from .models import EnrichmentTask, Flight

#: The exercise asks the queue view for the last three completed tasks.
COMPLETED_TASKS_SHOWN = 3
#: The flight table is unbounded input from an upstream feed, so it pages.
FLIGHTS_PER_PAGE = 25


class TaskListView(ListView):
    """The last few completed enrichment tasks and how they ended."""

    template_name = "flights/task_list.html"
    context_object_name = "tasks"

    def get_queryset(self):
        return (
            EnrichmentTask.objects.completed()
            .with_flight()
            .order_by("-completed_at")[:COMPLETED_TASKS_SHOWN]
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["shown"] = COMPLETED_TASKS_SHOWN
        context["total_completed"] = EnrichmentTask.objects.completed().count()
        return context


class FlightListView(ListView):
    """Key columns for every flight, filterable by route and enrichment state."""

    template_name = "flights/flight_list.html"
    context_object_name = "flights"
    paginate_by = FLIGHTS_PER_PAGE

    def get_queryset(self):
        queryset = Flight.objects.all()
        params = self.request.GET

        if origin := params.get("origin", "").strip():
            queryset = queryset.filter(origin__iexact=origin)
        if destination := params.get("destination", "").strip():
            queryset = queryset.filter(destination__iexact=destination)
        if cabin := params.get("cabin", "").strip():
            queryset = queryset.filter(travel_class=cabin)

        enriched = params.get("enriched", "").strip()
        if enriched in {"yes", "no"}:
            queryset = queryset.filter(enriched=enriched == "yes")

        return queryset

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        params = self.request.GET
        context["filters"] = {
            "origin": params.get("origin", ""),
            "destination": params.get("destination", ""),
            "cabin": params.get("cabin", ""),
            "enriched": params.get("enriched", ""),
        }
        context["cabins"] = CabinClass.choices
        context["has_filters"] = any(context["filters"].values())
        context["total_flights"] = Flight.objects.count()
        return context
