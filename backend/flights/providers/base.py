"""The port every price source implements."""

from __future__ import annotations

import abc

from ..dto import PriceQuery, PriceQuote


class PricingError(Exception):
    """Base class for every failure a provider can report."""


class TransientPricingError(PricingError):
    """The call may succeed if tried again (timeout, 5xx, rate limit).

    ``retry_after`` carries the provider's own advice in seconds when it gave
    any -- honouring it is the difference between backing off politely and
    hammering a rate-limited endpoint on a fixed timer.
    """

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class PermanentPricingError(PricingError):
    """The call will never succeed as written (bad credentials, bad request).

    Separating this from the transient case is what stops the task from
    burning its whole retry ladder on a malformed payload.
    """


class PriceUnavailable(PricingError):
    """The provider answered, but had no fare for this itinerary.

    Not an error condition for the pipeline: the flight is simply marked as
    checked with no price, and it is not retried.
    """


class PriceProvider(abc.ABC):
    """Fetch a retail fare for one itinerary.

    Implementations must be safe to construct once and reuse, and must
    translate every upstream failure into one of the three errors above.
    Anything else leaking out is a bug in the adapter, not in the caller.
    """

    #: Registry key, also written into the stored quote for traceability.
    name: str = ""

    @abc.abstractmethod
    def fetch(self, query: PriceQuery) -> PriceQuote:
        """Return a quote, or raise one of the ``PricingError`` subclasses."""

    def __repr__(self) -> str:
        return f"<{type(self).__name__} name={self.name!r}>"
