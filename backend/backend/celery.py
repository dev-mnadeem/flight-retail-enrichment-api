"""Celery application.

Configuration is read from Django settings under the ``CELERY_`` namespace,
so the broker URL and the eager flag come from the same ``.env`` the web
process uses -- there is no second place to configure the queue.
"""

from __future__ import annotations

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")

app = Celery("backend")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
