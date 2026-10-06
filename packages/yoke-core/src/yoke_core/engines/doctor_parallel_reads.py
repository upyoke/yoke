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

    def tasks():
        for value in values:
            remaining_seconds(CHECK_BUDGET_S)
            yield copy_context(), value

    pool = ThreadPoolExecutor(max_workers=READ_WORKERS)
    try:
        yield from pool.map(read, tasks(), timeout=remaining_seconds(CHECK_BUDGET_S))
    except TimeoutError as exc:
        raise DoctorBudgetExhausted("doctor_check_budget_exhausted") from exc
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def prefetched_text_reader(paths):
    """Read each UTF-8 source once; retain failures for the caller's skip policy."""

    def read(path):
        try:
            return path, path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return path, exc

    texts = dict(bounded_read_map(read, dict.fromkeys(paths)))

    def read_text(path, *, encoding="utf-8"):
        if path not in texts:
            return path.read_text(encoding=encoding)
        text = texts[path]
        if isinstance(text, Exception):
            raise text
        return text

    return read_text
