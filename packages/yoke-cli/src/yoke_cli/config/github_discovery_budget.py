"""Aggregate request, row, byte, and deadline budget for GitHub discovery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


MAX_DISCOVERY_REQUESTS = 200
MAX_DISCOVERY_ROWS = 10_000
MAX_DISCOVERY_RESPONSE_BYTES = 16 * 1024 * 1024
DISCOVERY_DEADLINE_SECONDS = 60.0


@dataclass
class DiscoveryBudget:
    deadline: float
    monotonic: Callable[[], float]
    error_type: type[RuntimeError]
    requests: int = 0
    rows: int = 0
    response_bytes: int = 0

    def before_request(self) -> float:
        remaining = self.deadline - self.monotonic()
        if remaining <= 0 or self.requests >= MAX_DISCOVERY_REQUESTS:
            raise self.error_type(
                "GitHub access discovery exceeded its total request/deadline budget"
            )
        self.requests += 1
        return remaining

    def add_response(self, size: int) -> None:
        self.response_bytes += size
        if self.response_bytes > MAX_DISCOVERY_RESPONSE_BYTES:
            raise self.error_type(
                "GitHub access discovery exceeded its total response-byte budget"
            )

    def add_rows(self, count: int) -> None:
        self.rows += count
        if self.rows > MAX_DISCOVERY_ROWS:
            raise self.error_type(
                "GitHub access discovery exceeded its total row budget"
            )


__all__ = [
    "DISCOVERY_DEADLINE_SECONDS",
    "DiscoveryBudget",
    "MAX_DISCOVERY_REQUESTS",
    "MAX_DISCOVERY_RESPONSE_BYTES",
    "MAX_DISCOVERY_ROWS",
]
