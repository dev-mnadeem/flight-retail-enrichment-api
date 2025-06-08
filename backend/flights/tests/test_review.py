from datetime import date
from decimal import Decimal

import pytest

from flights.dto import FareVerdict, PriceQuery, PriceQuote
from flights.enums import CabinClass, TripType
from flights.review import HeuristicFareReviewer, available_reviewers, get_reviewer
from flights.review.claude import ClaudeFareReviewer
from flights.review.heuristic import MIN_SCORABLE_DISTANCE_MILES

JFK_ATH_MILES = 6302


def query(cabin: CabinClass = CabinClass.BUSINESS) -> PriceQuery:
    return PriceQuery(
        origin="JFK",
        destination="ATH",
        outbound_date=date(2025, 6, 13),
        cabin=cabin,
        trip_type=TripType.ONE_WAY,
    )


def quote(amount: str) -> PriceQuote:
    return PriceQuote(amount=Decimal(amount), currency="USD", provider="fixture")


class TestRegistry:
    def test_lists_both_reviewers(self):
        assert available_reviewers() == ("claude", "heuristic")

    def test_default_is_the_offline_reviewer(self):
        assert get_reviewer().name == "heuristic"

    def test_unknown_name_degrades_rather_than_raising(self):
        assert get_reviewer("psychic").name == "heuristic"


class TestHeuristicFareReviewer:
    @pytest.fixture
    def reviewer(self) -> HeuristicFareReviewer:
        return HeuristicFareReviewer()

    def test_a_normal_business_fare_is_plausible(self, reviewer):
        verdict = reviewer.review(query(), quote("2570.40"), JFK_ATH_MILES)
        assert verdict.rating == FareVerdict.PLAUSIBLE

    def test_an_economy_price_in_a_business_cabin_reads_as_low(self, reviewer):
        # The exact failure mode of not sending a cabin to the provider.
        verdict = reviewer.review(query(), quote("612.00"), JFK_ATH_MILES)
        assert verdict.rating == FareVerdict.LOW

    def test_a_round_trip_total_read_as_one_way_reads_as_high(self, reviewer):
        verdict = reviewer.review(query(), quote("29000.00"), JFK_ATH_MILES)
        assert verdict.rating == FareVerdict.HIGH

    def test_short_hops_are_not_scored(self, reviewer):
        verdict = reviewer.review(query(), quote("120.00"), MIN_SCORABLE_DISTANCE_MILES - 1)
        assert verdict.rating == FareVerdict.UNKNOWN

    def test_rationale_names_the_band(self, reviewer):
        verdict = reviewer.review(query(), quote("2570.40"), JFK_ATH_MILES)
        assert "c/mi" in verdict.rationale
        assert verdict.cents_per_mile == pytest.approx(40.79, abs=0.05)

    def test_the_same_price_can_be_plausible_in_one_cabin_and_not_another(self, reviewer):
        cheap = quote("612.00")
        assert reviewer.review(query(CabinClass.ECONOMY), cheap, JFK_ATH_MILES).rating == (
            FareVerdict.PLAUSIBLE
        )
        assert reviewer.review(query(CabinClass.BUSINESS), cheap, JFK_ATH_MILES).rating == (
            FareVerdict.LOW
        )


class TestClaudeFareReviewer:
    def test_no_credentials_means_the_heuristic_answers(self):
        verdict = ClaudeFareReviewer(api_key="").review(query(), quote("2570.40"), JFK_ATH_MILES)
        assert verdict.reviewer == "heuristic"
        assert verdict.rating == FareVerdict.PLAUSIBLE

    def test_an_api_failure_falls_back_instead_of_raising(self, monkeypatch):
        reviewer = ClaudeFareReviewer(api_key="sk-not-real")
        monkeypatch.setattr(reviewer, "_get_client", lambda: object())
        monkeypatch.setattr(
            reviewer,
            "_ask",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("upstream down")),
        )
        verdict = reviewer.review(query(), quote("2570.40"), JFK_ATH_MILES)
        assert verdict.reviewer == "heuristic"

    def test_a_tool_call_is_turned_into_a_verdict(self, monkeypatch):
        class Block:
            type = "tool_use"
            name = "record_verdict"
            input = {"rating": FareVerdict.HIGH, "rationale": "Looks like a round-trip total."}

        class Response:
            content = [Block()]

        class Messages:
            def create(self, **kwargs):
                return Response()

        class Client:
            messages = Messages()

        reviewer = ClaudeFareReviewer(api_key="sk-not-real")
        monkeypatch.setattr(reviewer, "_get_client", lambda: Client())
        verdict = reviewer.review(query(), quote("2570.40"), JFK_ATH_MILES)
        assert verdict.reviewer == "claude"
        assert verdict.rating == FareVerdict.HIGH
        assert verdict.cents_per_mile is not None
