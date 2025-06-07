"""Boot Django before anything imports a model.

The FastAPI process uses Django purely as an ORM and task host. That means
``django.setup()`` has to run before the first ``from flights.models import
...`` anywhere in the import graph, and it has to run exactly once. Doing it
here, in a module with no other job, keeps that ordering explicit instead of
depending on the order of imports at the top of a route file.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DJANGO_ROOT = REPO_ROOT / "backend"

_ready = False


def setup_django() -> None:
    global _ready
    if _ready:
        return

    if str(DJANGO_ROOT) not in sys.path:
        sys.path.insert(0, str(DJANGO_ROOT))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")

    import django

    django.setup()
    _ready = True
