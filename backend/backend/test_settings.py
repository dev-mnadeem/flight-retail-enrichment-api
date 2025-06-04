"""Settings used by the test suite.

Pins the adapters so the suite is deterministic and offline whatever a
developer happens to have in their ``.env``: fixture fares, the heuristic
reviewer, and tasks executed inline instead of handed to a broker.
"""

from .settings import *  # noqa: F403

FLIGHT_PRICE_PROVIDER = "fixture"
FARE_REVIEWER = "heuristic"
SERPAPI_KEY = ""
ANTHROPIC_API_KEY = ""

CELERY_BROKER_URL = ""
CELERY_TASK_ALWAYS_EAGER = True

SECRET_KEY = "test-only-secret-key"  # noqa: S105
