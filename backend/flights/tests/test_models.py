from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError
from django.utils import timezone

from flights.enums import CabinClass, TaskStatus
from flights.models import EnrichmentTask, Flight, PriceQuoteCache

from .conftest import make_flight

pytestmark = pytest.mark.django_db


class TestFlight:
    def test_str_is_the_flight_id(self, flight):
        assert str(flight) == "20250613-MS-MS986-MS747"

    def test_flight_id_is_unique(self, flight):
        with pytest.raises(IntegrityError):
            make_flight()

    def test_total_distance_sums_the_legs(self, flight):
        assert flight.total_distance_miles == 5614 + 688

    def test_total_distance_tolerates_junk_legs(self, db):
        junk = make_flight(
            flight_id="junk-legs",
            legs=[{"distance": "not a number"}, {"distance": 500}, "not even a dict"],
        )
        assert junk.total_distance_miles == 500

    def test_cabin_parses_the_stored_label(self, flight):
        assert flight.cabin is CabinClass.BUSINESS

    def test_summary_is_abridged(self, flight):
        summary = flight.summary()
        assert summary["id"] == flight.flight_id
        assert summary["leg_count"] == 2
        # The full leg blobs are deliberately not in the abridged view.
        assert "legs" not in summary


class TestEnrichmentTask:
    def test_completed_excludes_in_flight_tasks(self, flight):
        EnrichmentTask.objects.create(task_id="a", flight=flight, status=TaskStatus.PENDING)
        EnrichmentTask.objects.create(task_id="b", flight=flight, status=TaskStatus.RETRYING)
        done = EnrichmentTask.objects.create(task_id="c", flight=flight, status=TaskStatus.SUCCESS)
        assert list(EnrichmentTask.objects.completed()) == [done]

    def test_with_flight_avoids_a_query_per_row(self, flight, django_assert_num_queries):
        for index in range(5):
            EnrichmentTask.objects.create(
                task_id=f"task-{index}", flight=flight, status=TaskStatus.SUCCESS
            )
        with django_assert_num_queries(1):
            rows = list(EnrichmentTask.objects.completed().with_flight())
            assert [row.flight.flight_id for row in rows] == [flight.flight_id] * 5

    def test_mark_stamps_completed_at_only_on_a_terminal_status(self, flight):
        task = EnrichmentTask.objects.create(task_id="t", flight=flight)
        task.mark(TaskStatus.STARTED)
        assert task.completed_at is None
        task.mark(TaskStatus.SUCCESS, {"retail_price": "100.00"})
        assert task.completed_at is not None
        assert task.result == {"retail_price": "100.00"}

    def test_deleting_a_flight_removes_its_tasks(self, flight):
        EnrichmentTask.objects.create(task_id="t", flight=flight)
        flight.delete()
        assert EnrichmentTask.objects.count() == 0


class TestPriceQuoteCache:
    def test_is_fresh_within_the_ttl(self, db):
        row = PriceQuoteCache.objects.create(
            query_hash="h",
            origin="JFK",
            destination="ATH",
            cabin="Business",
            amount=Decimal("2570.40"),
            currency="USD",
            provider="fixture",
        )
        assert row.is_fresh(ttl_seconds=3600)

    def test_is_stale_past_the_ttl(self, db):
        row = PriceQuoteCache.objects.create(
            query_hash="h",
            origin="JFK",
            destination="ATH",
            cabin="Business",
            amount=Decimal("2570.40"),
            currency="USD",
            provider="fixture",
        )
        PriceQuoteCache.objects.filter(pk=row.pk).update(
            fetched_at=timezone.now() - timedelta(hours=2)
        )
        row.refresh_from_db()
        assert not row.is_fresh(ttl_seconds=3600)


def test_flight_default_cabin_is_economy(db):
    flight = Flight.objects.create(
        flight_id="bare",
        origin="JFK",
        destination="LAX",
        departure_time=timezone.now(),
        arrival_time=timezone.now(),
        last_seen=timezone.now(),
    )
    assert flight.travel_class == CabinClass.ECONOMY.value
    assert flight.flight_numbers == []
    assert flight.legs == []
