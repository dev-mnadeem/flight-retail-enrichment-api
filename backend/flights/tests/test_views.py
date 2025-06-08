import pytest
from django.urls import reverse

from flights.enums import CabinClass, TaskStatus
from flights.models import EnrichmentTask
from flights.views import COMPLETED_TASKS_SHOWN, FLIGHTS_PER_PAGE

from .conftest import make_flight

pytestmark = pytest.mark.django_db


class TestFlightListView:
    def test_empty_state_is_rendered(self, client):
        response = client.get(reverse("flights:flight-list"))
        assert response.status_code == 200
        assert b"No flights yet." in response.content

    def test_lists_a_flight(self, client, flight):
        response = client.get(reverse("flights:flight-list"))
        assert flight.flight_id.encode() in response.content

    def test_filters_by_origin(self, client, flight, economy_flight):
        response = client.get(reverse("flights:flight-list"), {"destination": "lax"})
        assert response.context["flights"].count() == 1
        assert response.context["flights"].first().flight_id == economy_flight.flight_id

    def test_filters_by_cabin(self, client, flight, economy_flight):
        response = client.get(reverse("flights:flight-list"), {"cabin": CabinClass.BUSINESS.value})
        assert [row.flight_id for row in response.context["flights"]] == [flight.flight_id]

    def test_filters_by_enrichment_state(self, client, flight, economy_flight):
        economy_flight.enriched = True
        economy_flight.save(update_fields=["enriched"])
        response = client.get(reverse("flights:flight-list"), {"enriched": "no"})
        assert [row.flight_id for row in response.context["flights"]] == [flight.flight_id]

    def test_pages_a_long_list(self, client, db):
        for index in range(FLIGHTS_PER_PAGE + 3):
            make_flight(flight_id=f"bulk-{index:03d}")
        response = client.get(reverse("flights:flight-list"))
        assert response.context["is_paginated"] is True
        assert len(response.context["flights"]) == FLIGHTS_PER_PAGE

        second = client.get(reverse("flights:flight-list"), {"page": 2})
        assert len(second.context["flights"]) == 3

    def test_no_match_says_so(self, client, flight):
        response = client.get(reverse("flights:flight-list"), {"origin": "ZZZ"})
        assert b"No flights match those filters." in response.content


class TestTaskListView:
    def test_empty_state_is_rendered(self, client):
        response = client.get(reverse("flights:task-list"))
        assert response.status_code == 200
        assert b"Nothing has finished yet." in response.content

    def test_shows_only_the_last_completed_tasks(self, client, flight):
        for index in range(COMPLETED_TASKS_SHOWN + 2):
            EnrichmentTask.objects.create(
                task_id=f"done-{index}",
                flight=flight,
                status=TaskStatus.SUCCESS,
                completed_at=flight.last_seen,
            )
        response = client.get(reverse("flights:task-list"))
        assert len(response.context["tasks"]) == COMPLETED_TASKS_SHOWN
        assert response.context["total_completed"] == COMPLETED_TASKS_SHOWN + 2

    def test_hides_tasks_that_have_not_finished(self, client, flight):
        EnrichmentTask.objects.create(task_id="waiting", flight=flight, status=TaskStatus.PENDING)
        response = client.get(reverse("flights:task-list"))
        assert len(response.context["tasks"]) == 0

    def test_renders_the_flight_id_without_a_query_per_row(
        self, client, flight, django_assert_max_num_queries
    ):
        for index in range(COMPLETED_TASKS_SHOWN):
            EnrichmentTask.objects.create(
                task_id=f"joined-{index}",
                flight=flight,
                status=TaskStatus.SUCCESS,
                completed_at=flight.last_seen,
            )
        # One query for the tasks (joined), one for the total count.
        with django_assert_max_num_queries(2):
            response = client.get(reverse("flights:task-list"))
            assert flight.flight_id.encode() in response.content
