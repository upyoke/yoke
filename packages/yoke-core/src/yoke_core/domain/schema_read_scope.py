"""Bounded read sharing for one database operation, never across requests."""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

_READS = ContextVar("schema_read_scope", default=None)


@contextmanager
def composition_reads():
    """Nested composition helpers share a cache; the outer exit discards it."""
    if _READS.get() is not None:
        yield
        return
    token = _READS.set({})
    try:
        yield
    finally:
        _READS.reset(token)


def shared_read(conn, key, reader):
    """Share immutable facts only, scoped to the actual connection object."""
    cache = _READS.get()
    if cache is None:
        return reader()
    scoped_key = (conn, key)
    if scoped_key not in cache:
        cache[scoped_key] = reader()
    return cache[scoped_key]


def composition_operation(function):
    @wraps(function)
    def run(*args, **kwargs):
        with composition_reads():
            return function(*args, **kwargs)

    return run


def reads_active():
    return _READS.get() is not None


def discard_read(conn, key):
    """Invalidate a fact when this operation binds its previously unset source."""
    cache = _READS.get()
    if cache is not None:
        cache.pop((conn, key), None)
