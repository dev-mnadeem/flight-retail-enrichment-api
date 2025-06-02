import pytest

pytestmark = pytest.mark.django_db(transaction=True)


class TestListFlights:
    def test_empty_database(self, client):
        body = client.get("/flights").json()
        assert body == {"items": [], "total": 0, "limit": 25, "offset": 0}

    def test_lists_an_enriched_flight_with_its_currency(self, client, sample_flight):
        client.post("/enrich-flight", json=sample_flight)
        body = client.get("/flights").json()

        assert body["total"] == 1
        item = body["items"][0]
        assert item["id"] == sample_flight["id"]
        assert item["retail_price"] == "2570.40"
        assert item["currency"] == "USD"
        assert item["enriched"] is True

    def test_filters_by_route(self, client, sample_flight):
        client.post("/enrich-flight", json=sample_flight)
        client.post("/enrich-flight", json=dict(sample_flight, id="lax-1", destination="LAX"))

        assert client.get("/flights", params={"destination": "ath"}).json()["total"] == 1
        assert client.get("/flights", params={"destination": "lax"}).json()["total"] == 1

    def test_paginates(self, client, sample_flight):
        for index in range(4):
            client.post("/enrich-flight", json=dict(sample_flight, id=f"page-{index}"))

        body = client.get("/flights", params={"limit": 2, "offset": 2}).json()
        assert body["total"] == 4
        assert len(body["items"]) == 2

    def test_caps_the_page_size(self, client):
        # An unbounded list endpoint over a feed-fed table is a table scan.
        assert client.get("/flights", params={"limit": 5000}).status_code == 422


class TestGetFlight:
    def test_unknown_flight_is_a_404(self, client):
        assert client.get("/flights/nope").status_code == 404

    def test_returns_one_flight(self, client, sample_flight):
        client.post("/enrich-flight", json=sample_flight)
        body = client.get(f"/flights/{sample_flight['id']}").json()
        assert body["id"] == sample_flight["id"]
        assert body["fare_review"]["rating"] == "plausible"


class TestHealth:
    def test_reports_the_wired_adapters(self, client):
        body = client.get("/healthz").json()
        assert body["status"] == "ok"
        assert body["database"] == "ok"
        assert body["price_provider"] == "fixture"
        assert body["fare_reviewer"] == "heuristic"
        assert body["celery_eager"] is True


class TestRoot:
    def test_redirects_to_the_docs(self, client):
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == "/docs"
