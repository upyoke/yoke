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


@dataclass(frozen=True)
class _FormField:
    """One labelled box in a view that collects several values at once.

    ``key`` names the value in the dict the view hands to its ``on_done`` and
    seeds the widget ids below, so a field's box and its inline error slot are
    addressable on their own — an invalid paste marks the field it came from
    rather than every field on the screen.
    """

    key: str
    label: str
    placeholder: str
    password: bool = False
    validate: Callable[[str], str | None] | None = None

    @property
    def input_id(self) -> str:
        return f"onboard-input-{self.key}"

    @property
    def error_id(self) -> str:
        return f"onboard-input-error-{self.key}"


@dataclass
class _PendingForm:
    """A multi-field view awaiting one submission carrying every value.

    The single-field :class:`_PendingInput` commits on its own Enter; a form
    commits once — from Enter on its last field or from the row that submits it
    — so the values that belong together are collected on one screen.
    """

    fields: tuple[_FormField, ...]
    on_done: Callable[[dict[str, str]], None]


__all__ = ["_FormField", "_PendingForm", "_PendingInput", "_View"]
