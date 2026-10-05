"""Enforce check deadlines in Python without unwinding database protocols.

Tracing is thread-local and restored after each check. Native database calls
suppress deadline exceptions until the protocol returns; their statement
timeout owns cancellation, and the adapter checks the clock afterwards.
"""

from __future__ import annotations

import dis
import sys
import time
from contextvars import ContextVar

from yoke_contracts.doctor_budget import (
    CHECK_BUDGET_S,
    DoctorBudgetExhausted,
    remaining_seconds,
)

_driver_active: ContextVar[bool] = ContextVar("doctor_driver_active", default=False)


def driver_call(method, *args, **kwargs):
    """Finish a driver operation before a Python deadline can unwind it."""
    token = _driver_active.set(True)
    try:
        return method(*args, **kwargs)
    except Exception as exc:
        if getattr(exc, "sqlstate", None) == "57014":
            raise DoctorBudgetExhausted("doctor_check_budget_exhausted") from exc
        raise
    finally:
        _driver_active.reset(token)


def run_wall_clock_bounded(method, *args):
    """Trace loops and recursive calls; finite straight-line frames need no trace.

    The owning frame starts before tracing is installed, so its finally always
    restores the caller's trace even when an expired call event unwinds a check.
    """
    previous = sys.gettrace()
    clock = time.monotonic
    deadline = clock() + remaining_seconds(CHECK_BUDGET_S)
    looping_codes = {}

    def trace(frame, event, arg):
        if clock() >= deadline and not _driver_active.get():
            raise DoctorBudgetExhausted("doctor_check_budget_exhausted")
        if event == "call":
            code = frame.f_code
            loops = looping_codes.get(code)
            if loops is None:
                loops = looping_codes[code] = any(
                    (
                        instruction.opcode in dis.hasjrel
                        or instruction.opcode in dis.hasjabs
                    )
                    and isinstance(instruction.argval, int)
                    and instruction.argval <= instruction.offset
                    for instruction in dis.get_instructions(code)
                )
            if not loops:
                return None
        return trace

    sys.settrace(trace)
    try:
        return method(*args)
    finally:
        sys.settrace(previous)
