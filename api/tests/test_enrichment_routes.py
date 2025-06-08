"""End-to-end over the HTTP surface.

The whole pipeline runs inline here -- no broker, no network, no key -- so
these assert real prices rather than just that a 202 came back.
"""

import pytest

pytestmark = pytest.mark.django_db(transaction=True)


class TestEnrichFlight:
    def test_accepts_the_exercise_payload(self, client, sample_flight):
        response = client.post("/enrich-flight", json=sample_flight)
        assert response.status_code == 202
        body = response.json()
        assert body["flight_id"] == sample_flight["id"]
        assert body["task_id"]

    def test_string_layover_times_are_coerced(self, client, sample_flight):
        # The exercise payload sends layover_time as "235.0", a string.
        assert client.post("/enrich-flight", json=sample_flight).status_code == 202

    def test_rejects_a_payload_with_no_id(self, client, sample_flight):
        del sample_flight["id"]
        assert client.post("/enrich-flight", json=sample_flight).status_code == 422

    def test_rejects_an_oversized_airport_code(self, client, sample_flight):
        sample_flight["origin"] = "NEW YORK KENNEDY"
        assert client.post("/enrich-flight", json=sample_flight).status_code == 422

    def test_resubmitting_updates_rather_than_duplicating(self, client, sample_flight):
        from flights.models import Flight

        client.post("/enrich-flight", json=sample_flight)
        sample_flight["travel_class"] = "Economy"
        client.post("/enrich-flight", json=sample_flight)

        assert Flight.objects.count() == 1
        assert Flight.objects.get().travel_class == "Economy"


class TestTaskStatus:
    def test_unknown_task_is_a_404(self, client):
        response = client.get("/task-status/not-a-real-task")
        assert response.status_code == 404
        assert response.json()["detail"] == "Task not found"

    def test_returns_status_price_and_abridged_flight(self, client, sample_flight):
        task_id = client.post("/enrich-flight", json=sample_flight).json()["task_id"]
        body = client.get(f"/task-status/{task_id}").json()

        assert body["status"] == "SUCCESS"
        assert body["result"]["retail_price"] == "2570.40"
        assert body["result"]["currency"] == "USD"
        # The exercise asks for abridged flight info alongside the status.
        assert body["flight"]["id"] == sample_flight["id"]
        assert body["flight"]["leg_count"] == 2

    def test_carries_the_fare_review(self, client, sample_flight):
        task_id = client.post("/enrich-flight", json=sample_flight).json()["task_id"]
        review = client.get(f"/task-status/{task_id}").json()["result"]["review"]
        assert review["rating"] == "plausible"
        assert review["reviewer"] == "heuristic"


class TestBatchEnrichment:
    def test_queues_every_valid_entry(self, client, sample_flight):
        second = dict(sample_flight, id="20250614-AA-AA1", destination="LAX")
        response = client.post("/enrich-flights", json={"flights": [sample_flight, second]})

        assert response.status_code == 202
        body = response.json()
        assert body["submitted"] == 2
        assert body["accepted"] == 2
        assert body["rejected"] == 0

    def test_one_bad_entry_does_not_sink_the_batch(self, client, sample_flight, monkeypatch):
        from api.routers import enrichment as enrichment_module

        real_enqueue = enrichment_module.enqueue

        def flaky(flight):
            if flight.flight_id.endswith("-BAD"):
                raise RuntimeError("broker refused this one")
            return real_enqueue(flight)

        monkeypatch.setattr(enrichment_module, "enqueue", flaky)

        bad = dict(sample_flight, id="20250614-XX-BAD")
        response = client.post("/enrich-flights", json={"flights": [sample_flight, bad]})

        body = response.json()
        assert body["accepted"] == 1
        assert body["rejected"] == 1
        failed = next(item for item in body["results"] if not item["accepted"])
        assert failed["flight_id"] == "20250614-XX-BAD"
        assert "broker refused" in failed["error"]

    def test_rejects_an_empty_batch(self, client):
        assert client.post("/enrich-flights", json={"flights": []}).status_code == 422
