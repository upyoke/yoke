"""Overlap independent Doctor reads under one shared deadline, in input order."""

from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

from yoke_contracts.doctor_budget import (
    CHECK_BUDGET_S,
    DoctorBudgetExhausted,
    remaining_seconds,
)

READ_WORKERS = 8


def bounded_read_map(method, values):
    """Copy the caller budget into each read; cancel queued reads on expiry.

    Read methods must bound native blocking operations with remaining_seconds.
    Returning in input order keeps report ordering independent of scheduling.
    """

    def read(task):
        context, value = task
        return context.run(method, value)

    pool = ThreadPoolExecutor(max_workers=READ_WORKERS)
    try:
        tasks = ((copy_context(), value) for value in values)
        yield from pool.map(read, tasks, timeout=remaining_seconds(CHECK_BUDGET_S))
    except TimeoutError as exc:
        raise DoctorBudgetExhausted("doctor_check_budget_exhausted") from exc
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
