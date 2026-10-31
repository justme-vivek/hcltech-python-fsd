import time
from enum import Enum

class State(str, Enum):
    CLOSED="CLOSED"; OPEN="OPEN"; HALF_OPEN="HALF-OPEN"

class CircuitBreaker:
    def __init__(self, threshold=3, reset_seconds=10):
        self.threshold, self.reset_seconds = threshold, reset_seconds
        self.failures, self.opened_at, self.state = 0, None, State.CLOSED

    def allow(self):
        if self.state == State.OPEN and time.monotonic() - self.opened_at >= self.reset_seconds:
            self.state = State.HALF_OPEN
            return True
        return self.state != State.OPEN

    def success(self):
        self.failures, self.opened_at, self.state = 0, None, State.CLOSED

    def failure(self):
        self.failures += 1
        if self.failures >= self.threshold or self.state == State.HALF_OPEN:
            self.state, self.opened_at = State.OPEN, time.monotonic()

    def call(self, fn, fallback=None):
        if not self.allow():
            raise RuntimeError("Circuit breaker is OPEN")
        try:
            result = fn()
            self.success()
            return result
        except Exception:
            self.failure()
            if fallback is not None:
                return fallback
            raise
