"""Share current QA facts within one evaluation, independently of source caches."""

from contextvars import ContextVar
from contextlib import contextmanager
from functools import wraps

from yoke_core.domain.schema_read_scope import composition_reads

_PRESENTATION = ContextVar("deployment_qa_presentation", default=None)
_RECORDED_SOURCE = ContextVar("deployment_recorded_source_presentation", default=False)


def presentation_operation(function):
    @wraps(function)
    def run(*args, **kwargs):
        token = _PRESENTATION.set({}) if not presentation_active() else None
        try:
            # Immutable source answers may be reused by the enclosing operation;
            # mutable QA facts belong only to this evaluation after its locks.
            with composition_reads():
                return function(*args, **kwargs)
        finally:
            if token is not None:
                _PRESENTATION.reset(token)

    return run


def presentation_active():
    return _PRESENTATION.get() is not None


def presentation_read(conn, key, reader):
    cache = _PRESENTATION.get()
    if cache is None:
        return reader()
    scoped_key = (conn, key)
    if scoped_key not in cache:
        cache[scoped_key] = reader()
    return cache[scoped_key]


@contextmanager
def recorded_source_presentation(*, enabled=True):
    """Display recorded exact-target QA; source proof belongs to admission/gates.

    This read still resolves current attachments, withdrawals and case/target
    identities. It cannot authorize execution, create evidence or settle a gate.
    """
    if not enabled:
        yield
        return
    token = _RECORDED_SOURCE.set(True)
    try:
        yield
    finally:
        _RECORDED_SOURCE.reset(token)


def presentation_requires_candidate_source():
    return not _RECORDED_SOURCE.get()


@contextmanager
def uncached_presentation():
    """Acceptance writes re-read their own subject under its lock, outside the snapshot."""
    from yoke_core.domain.deployment_qa_presentation_facts import _MEMBERS

    cache = _PRESENTATION.set(None)
    members = _MEMBERS.set(None)
    try:
        yield
    finally:
        _MEMBERS.reset(members)
        _PRESENTATION.reset(cache)
