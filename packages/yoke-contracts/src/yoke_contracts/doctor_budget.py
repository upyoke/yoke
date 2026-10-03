"""Doctor's operation deadlines, shared by checks and their I/O transports.

The check deadline is context-local: concurrent hosted requests cannot shorten
each other's work. I/O uses the remaining budget rather than starting another
full timeout. Budget exhaustion escapes best-effort ``except Exception`` probes.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar

CHECK_BUDGET_S = 45.0
CHUNK_BUDGET_S = 60.0
RUN_BUDGET_S = 900.0
CHUNK_ATTEMPTS = 2
_deadline: ContextVar[float | None] = ContextVar("doctor_deadline", default=None)


class DoctorBudgetExhausted(BaseException):
    """An incomplete check must unwind even through best-effort probes."""


def remaining_seconds(timeout: float) -> float:
    deadline = _deadline.get()
    if deadline is None:
        return timeout
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise DoctorBudgetExhausted("doctor_check_budget_exhausted")
    return min(timeout, remaining)


def bound_deadline(deadline: float) -> float:
    active = _deadline.get()
    if active is None:
        return deadline
    remaining_seconds(CHECK_BUDGET_S)
    return min(deadline, active)


@contextmanager
def check_budget():
    token = _deadline.set(time.monotonic() + CHECK_BUDGET_S)
    try:
        yield
    finally:
        try:
            remaining_seconds(CHECK_BUDGET_S)
        finally:
            _deadline.reset(token)
