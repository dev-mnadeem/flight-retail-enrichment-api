"""Django project package.

Importing the Celery app here is what makes ``@shared_task`` bind to it when
Django starts, rather than only when a worker boots.
"""

from .celery import app as celery_app

__all__ = ["celery_app"]
