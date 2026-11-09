"""Share read-only Markdown analysis within one corpus validation."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache

from markdown_it import MarkdownIt

_CACHE = ContextVar("documentation_markdown_cache", default=None)


def _parse(markdown: str, mode: str):
    parser = MarkdownIt("commonmark")
    if mode == "blocks":
        parser.disable("inline")
    elif mode == "visuals":
        parser.enable("table")
    return tuple(parser.parse(markdown))


def parse_markdown(markdown: str, *, mode: str = "commonmark"):
    """Return tokens for read-only consumers; key by exact text and grammar."""
    parse = _CACHE.get() or _parse
    return parse(markdown, mode)


@contextmanager
def markdown_analysis_scope():
    """Bound reuse to this validation, never to a path or a mutable file."""
    if _CACHE.get() is not None:
        yield
        return
    cached = lru_cache(maxsize=1024)(_parse)
    token = _CACHE.set(cached)
    try:
        yield
    finally:
        _CACHE.reset(token)
        cached.cache_clear()
