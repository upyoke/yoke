"""Request-scoped transport pool supplied by an embedding CLI caller."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable, Iterator

_Opener = Callable[..., Any]
_CURRENT: ContextVar[_Opener | None] = ContextVar("yoke_http_opener", default=None)


@contextmanager
def use_http_opener(opener: _Opener) -> Iterator[None]:
    """Use the resident pool for function calls in this hook thread only."""
    token = _CURRENT.set(opener)
    try:
        yield
    finally:
        _CURRENT.reset(token)


def active_http_opener() -> _Opener | None:
    return _CURRENT.get()
