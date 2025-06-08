from flights.enums import CabinClass, TaskStatus, TripType


class TestCabinClass:
    def test_serpapi_codes_cover_every_cabin(self):
        assert [cabin.serpapi_code for cabin in CabinClass] == [1, 2, 3, 4]

    def test_parse_is_case_and_space_insensitive(self):
        assert CabinClass.parse("BUSINESS") is CabinClass.BUSINESS
        assert CabinClass.parse("  premium   economy ") is CabinClass.PREMIUM_ECONOMY

    def test_parse_falls_back_to_economy(self):
        # Guessing a higher cabin would over-state the fare band and mask a
        # genuinely wrong price, so an unknown label must read as economy.
        assert CabinClass.parse("Sleeper Pod") is CabinClass.ECONOMY


class TestTripType:
    def test_serpapi_codes(self):
        assert TripType.ROUND_TRIP.serpapi_code == 1
        assert TripType.ONE_WAY.serpapi_code == 2


class TestTaskStatus:
    def test_terminal_excludes_in_flight_states(self):
        terminal = TaskStatus.terminal()
        assert TaskStatus.SUCCESS in terminal
        assert TaskStatus.FAILURE in terminal
        assert TaskStatus.RETRYING not in terminal
        assert TaskStatus.PENDING not in terminal
