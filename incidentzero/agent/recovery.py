from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

from incidentzero.model.errors import PermanentModelError, TransientModelError

T = TypeVar("T")


class RetryPolicy:
    """Bounded exponential-backoff retry for transient model errors only.

    Retries are attempted only for TransientModelError (e.g. HTTP 429,
    timeouts, 5xx).  PermanentModelError, schema errors, and any other
    exception propagate immediately — the controller must handle them
    through re-planning or escalation, not by retrying blindly.
    """

    def __init__(
        self,
        max_attempts: int = 3,
        initial_delay: float = 1.0,
        backoff_factor: float = 2.0,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.max_attempts = max_attempts
        self.initial_delay = initial_delay
        self.backoff_factor = backoff_factor
        self.sleeper = sleeper

    def call_model(self, fn: Callable[[], T]) -> T:
        """Call *fn* with bounded retry on TransientModelError.

        Raises the last TransientModelError if all attempts are exhausted.
        Any other exception (including PermanentModelError) propagates
        immediately without retrying.
        """
        last_error: TransientModelError | None = None
        for attempt in range(self.max_attempts):
            try:
                return fn()
            except TransientModelError as exc:
                last_error = exc
                if attempt < self.max_attempts - 1:
                    delay = self.initial_delay * (self.backoff_factor ** attempt)
                    self.sleeper(delay)
            # PermanentModelError and all other exceptions propagate immediately
        raise last_error  # type: ignore[misc]
