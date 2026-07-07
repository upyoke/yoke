"""Small shared state records for the onboarding wizard UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from textual.widgets import Static


@dataclass
class _View:
    """A body view: which step it belongs to, how to build it, what selecting does."""

    step: str
    builder: Callable[[], Iterable[Static]]
    on_select: Callable[[str], None] | None = None


@dataclass
class _PendingInput:
    on_done: Callable[[str], None]
    placeholder: str
    allow_placeholder: bool = True
    validate: Callable[[str], str | None] | None = None


__all__ = ["_PendingInput", "_View"]
