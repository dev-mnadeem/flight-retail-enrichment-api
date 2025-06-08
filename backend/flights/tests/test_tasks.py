from decimal import Decimal

import pytest

from flights.enums import TaskStatus
from flights.models import EnrichmentTask
from flights.providers.base import PermanentPricingError, TransientPricingError
from flights.tasks import MAX_RETRIES, enqueue, enrich_flight_task

pytestmark = pytest.mark.django_db


class TestEnqueue:
    def test_runs_inline_and_reaches_success(self, flight):
        task = enqueue(flight)
        assert task.status == TaskStatus.SUCCESS
        assert task.result["retail_price"] == "2570.40"
        assert task.completed_at is not None

        flight.refresh_from_db()
        assert flight.retail_price == Decimal("2570.40")

    def test_records_one_attempt_on_a_clean_run(self, flight):
        assert enqueue(flight).attempts == 1


class TestEnrichFlightTask:
    def test_a_missing_flight_fails_without_retrying(self, flight):
        # The row will never appear, so burning the retry ladder on it only
        # delays the failure while holding a worker slot.
        task = EnrichmentTask.objects.create(task_id="missing", flight=flight)
        result = enrich_flight_task.apply(args=["does-not-exist"], task_id="missing")

        task.refresh_from_db()
        assert task.status == TaskStatus.FAILURE
        assert "not found" in task.result["error"]
        assert result.result["error"] == task.result["error"]

    def test_a_transient_error_climbs_the_whole_retry_ladder(self, flight, monkeypatch):
        calls = _count_calls(monkeypatch, TransientPricingError("rate limited", retry_after=45))
        task = EnrichmentTask.objects.create(task_id="transient", flight=flight)

        enrich_flight_task.apply(args=[flight.flight_id], task_id="transient")

        # One first attempt plus MAX_RETRIES retries, then it gives up.
        assert calls["n"] == MAX_RETRIES + 1
        task.refresh_from_db()
        assert task.status == TaskStatus.FAILURE
        assert "gave up after 4 attempts" in task.result["error"]

    def test_the_providers_retry_after_beats_the_default_backoff(self, flight, monkeypatch):
        _count_calls(monkeypatch, TransientPricingError("rate limited", retry_after=45))
        task = EnrichmentTask.objects.create(task_id="backoff", flight=flight)

        seen: list[int] = []
        original_mark = EnrichmentTask.mark

        def record(self, status, result=None):
            if status == TaskStatus.RETRYING:
                seen.append(result["retry_in_seconds"])
            return original_mark(self, status, result)

        monkeypatch.setattr(EnrichmentTask, "mark", record)
        enrich_flight_task.apply(args=[flight.flight_id], task_id="backoff")

        assert seen == [45] * MAX_RETRIES
        assert task.task_id == "backoff"

    def test_a_permanent_error_is_attempted_exactly_once(self, flight, monkeypatch):
        # A bad key or a malformed response fails identically on every
        # attempt, so retrying it only delays the failure.
        calls = _count_calls(monkeypatch, PermanentPricingError("bad key"))
        task = EnrichmentTask.objects.create(task_id="permanent", flight=flight)

        result = enrich_flight_task.apply(args=[flight.flight_id], task_id="permanent")

        assert calls["n"] == 1
        assert isinstance(result.result, PermanentPricingError)
        task.refresh_from_db()
        assert task.status == TaskStatus.FAILURE
        assert task.result["error"] == "bad key"

    def test_runs_untracked_when_there_is_no_task_row(self, flight):
        # An error handler that itself raises because the tracking row is
        # missing masks whatever actually went wrong.
        result = enrich_flight_task.apply(args=[flight.flight_id], task_id="never-created")
        assert result.result["retail_price"] == "2570.40"

        flight.refresh_from_db()
        assert flight.enriched is True


def _count_calls(monkeypatch, error: Exception) -> dict[str, int]:
    """Replace the pipeline with one that always raises, counting attempts."""
    calls = {"n": 0}

    def always_fail(self, flight):
        calls["n"] += 1
        raise error

    monkeypatch.setattr("flights.tasks.EnrichmentService.enrich", always_fail)
    return calls
