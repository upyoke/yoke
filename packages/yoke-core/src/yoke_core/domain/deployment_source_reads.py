"""Reuse prepared source answers while locked validation rereads durable facts."""

import reprlib
from contextlib import contextmanager
from contextvars import ContextVar

from yoke_core.domain.domain_refusal import DomainRefusal
from yoke_core.domain.schema_read_scope import shared_read

_VALIDATING = ContextVar("deployment_source_validation", default=False)
# Name the exact question with whole SHAs; long commit lists are elided.
_KEY_REPR = reprlib.Repr()
_KEY_REPR.maxstring = 120
_KEY_REPR.maxtuple = 8
_KEY_REPR.maxlevel = 4


class SourcePreparationChanged(DomainRefusal, ValueError):
    """A changed source question needs a new unlocked preparation."""

    def __init__(self, message, prepare):
        super().__init__(message)
        self.prepare = prepare


def source_read(conn, key, reader):
    """One exact source question per operation; no provider work under locks."""

    def read():
        if _VALIDATING.get():
            raise SourcePreparationChanged(
                "deployment_source_preparation_changed: locked validation needs "
                f"source fact {_KEY_REPR.repr(key)}, which was not prepared; nothing was "
                "dispatched. Re-drive the same run to prepare its current "
                "source facts before acquiring item/run locks.",
                lambda: shared_read(conn, key, reader),
            )
        return reader()

    return shared_read(conn, key, read)


@contextmanager
def prepared_sources_only():
    token = _VALIDATING.set(True)
    try:
        yield
    finally:
        _VALIDATING.reset(token)
