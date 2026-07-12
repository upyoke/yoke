"""Operation-wide resource budget for GitHub App repository binding proof."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import time
from typing import Callable


GITHUB_BINDING_VERIFICATION_MAX_REQUESTS = 64
GITHUB_BINDING_VERIFICATION_MAX_ROWS = 10_000
GITHUB_BINDING_VERIFICATION_MAX_BYTES = 32 * 1024 * 1024


class GitHubBindingVerificationBudgetError(ValueError):
    """A binding proof exhausted its bounded execution envelope."""


@dataclass
class GitHubBindingVerificationBudget:
    """One deadline plus cumulative request, row, and response-byte limits."""

    deadline: float
    max_requests: int = GITHUB_BINDING_VERIFICATION_MAX_REQUESTS
    max_rows: int = GITHUB_BINDING_VERIFICATION_MAX_ROWS
    max_bytes: int = GITHUB_BINDING_VERIFICATION_MAX_BYTES
    clock: Callable[[], float] = field(default=time.monotonic, repr=False)
    requests_used: int = 0
    rows_used: int = 0
    bytes_used: int = 0

    @classmethod
    def for_operation(
        cls,
        timeout_seconds: float,
        *,
        max_requests: int = GITHUB_BINDING_VERIFICATION_MAX_REQUESTS,
        max_rows: int = GITHUB_BINDING_VERIFICATION_MAX_ROWS,
        max_bytes: int = GITHUB_BINDING_VERIFICATION_MAX_BYTES,
        clock: Callable[[], float] = time.monotonic,
    ) -> "GitHubBindingVerificationBudget":
        """Start a budget whose deadline covers the complete binding proof."""
        try:
            timeout = float(timeout_seconds)
        except (TypeError, ValueError, OverflowError) as exc:
            raise GitHubBindingVerificationBudgetError(
                "GitHub binding verification timeout must be positive and finite"
            ) from exc
        if not math.isfinite(timeout) or timeout <= 0:
            raise GitHubBindingVerificationBudgetError(
                "GitHub binding verification timeout must be positive and finite"
            )
        for value, label in (
            (max_requests, "request"),
            (max_rows, "row"),
            (max_bytes, "byte"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise GitHubBindingVerificationBudgetError(
                    f"GitHub binding verification {label} budget must be positive"
                )
        return cls(
            deadline=clock() + timeout,
            max_requests=max_requests,
            max_rows=max_rows,
            max_bytes=max_bytes,
            clock=clock,
        )

    def begin_request(self) -> float:
        """Reserve one request and return only the operation time remaining."""
        remaining = self._remaining_seconds()
        if self.requests_used >= self.max_requests:
            raise GitHubBindingVerificationBudgetError(
                "GitHub binding verification request budget exhausted"
            )
        self.requests_used += 1
        return remaining

    def consume_response_bytes(self, count: int) -> None:
        """Charge a complete response before any of its proof is trusted."""
        self.checkpoint()
        self.bytes_used += _nonnegative_count(count, "response byte")
        if self.bytes_used > self.max_bytes:
            raise GitHubBindingVerificationBudgetError(
                "GitHub binding verification byte budget exhausted"
            )

    def consume_rows(self, count: int) -> None:
        """Charge every raw collection row before searching the page."""
        self.checkpoint()
        self.rows_used += _nonnegative_count(count, "row")
        if self.rows_used > self.max_rows:
            raise GitHubBindingVerificationBudgetError(
                "GitHub binding verification row budget exhausted"
            )

    def checkpoint(self) -> None:
        """Reject work that has crossed the operation deadline."""
        self._remaining_seconds()

    def _remaining_seconds(self) -> float:
        remaining = self.deadline - self.clock()
        if remaining <= 0:
            raise GitHubBindingVerificationBudgetError(
                "GitHub binding verification deadline exceeded"
            )
        return remaining


def _nonnegative_count(value: int, label: str) -> int:
    if isinstance(value, bool) or int(value) < 0:
        raise GitHubBindingVerificationBudgetError(
            f"GitHub binding verification {label} count is invalid"
        )
    return int(value)


__all__ = [
    "GITHUB_BINDING_VERIFICATION_MAX_BYTES",
    "GITHUB_BINDING_VERIFICATION_MAX_REQUESTS",
    "GITHUB_BINDING_VERIFICATION_MAX_ROWS",
    "GitHubBindingVerificationBudget",
    "GitHubBindingVerificationBudgetError",
]
