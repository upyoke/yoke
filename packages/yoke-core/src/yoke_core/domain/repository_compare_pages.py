"""Comparison pages between two full commit ids, kept across requests.

A run pins its source revisions as full object ids when it is created, and a
comparison between two full ids lists the same commits forever. Every poll of
an unstarted run derives its carried work again, so without this the same
comparison was asked of the repository host on each one. Only pairs of full
ids are kept; a branch or abbreviated ref can move and is always asked.
Opening the source still checks the project's current authority.
"""

from __future__ import annotations

from collections import OrderedDict
from threading import Lock
from typing import Any, Callable, Mapping

from yoke_core.domain.deployment_run_compare_response import FULL_SHA_LENGTH, is_hex

PAGE_LIMIT = 512
_PAGES: OrderedDict[tuple[str, str, str, int], Mapping[str, Any]] = OrderedDict()
_LOCK = Lock()


def _immutable(sha: str) -> bool:
    return len(sha) == FULL_SHA_LENGTH and is_hex(sha)


def compare_page(
    location: str,
    base: str,
    head: str,
    page: int,
    read: Callable[[], Mapping[str, Any]],
) -> Mapping[str, Any]:
    """Serve one page of ``base...head`` from memory, reading it once."""
    if not (location and _immutable(base) and _immutable(head)):
        return read()
    key = (location, base.lower(), head.lower(), int(page))
    with _LOCK:
        if key in _PAGES:
            _PAGES.move_to_end(key)
            return _PAGES[key]
    body = read()
    with _LOCK:
        _PAGES[key] = body
        _PAGES.move_to_end(key)
        while len(_PAGES) > PAGE_LIMIT:
            _PAGES.popitem(last=False)
    return body


def forget_compare_pages() -> None:
    """Drop every kept page; tests that fake the host call this between cases."""
    with _LOCK:
        _PAGES.clear()


__all__ = ["PAGE_LIMIT", "compare_page", "forget_compare_pages"]
