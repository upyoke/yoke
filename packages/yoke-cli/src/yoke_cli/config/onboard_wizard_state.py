"""Small shared state records for the onboarding wizard UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from textual.widgets import Static

from yoke_cli.config.setup_prompt import SetupField, SetupPrompt


@dataclass(frozen=True)
class CopyTarget:
    """One exact string a view offers to the clipboard, and to a browser.

    ``label`` names it in the footer hint and the confirmation, so the
    operator always knows which of a screen's strings the key acted on.
    ``is_url`` marks the ones the open key can hand to a browser.
    """

    label: str
    value: str
    is_url: bool = False


@dataclass
class _View:
    """A body view: the question it asks, how to draw it, what answering does.

    ``prompt`` is required: it is the question both setup shells read, so a
    screen cannot exist without one. ``builder`` defaults to the standard body
    rendered from the prompt; bespoke layouts pass their own. ``on_select``
    takes a chosen row value, or the typed value of an input screen;
    ``on_form`` takes a form screen's field values. ``copy_targets`` are the
    URLs and one-time codes this view shows; the shell's copy and open keys act
    on them for as long as it is on screen.
    """

    prompt: SetupPrompt
    on_select: Callable[[str], None] | None = None
    builder: Callable[[], Iterable[Static]] | None = None
    copy_targets: tuple[CopyTarget, ...] = ()
    on_form: Callable[[dict[str, str]], None] | None = None
    # The row value last chosen here; a Back re-render starts its list on it.
    chosen: str | None = None

    def __post_init__(self) -> None:
        if self.builder is None:
            from yoke_cli.config.setup_prompt_render import render

            prompt = self.prompt
            self.builder = lambda: render(prompt)

    @property
    def step(self) -> str:
        return self.prompt.step


@dataclass
class _PendingInput:
    on_done: Callable[[str], None]
    placeholder: str
    allow_placeholder: bool = True
    validate: Callable[[str], str | None] | None = None


@dataclass
class _PendingForm:
    """A multi-field view awaiting one submission carrying every value.

    The single-field :class:`_PendingInput` commits on its own Enter; a form
    commits once — from Enter on its last field or from the row that submits it
    — so the values that belong together are collected on one screen.
    """

    fields: tuple[SetupField, ...]
    on_done: Callable[[dict[str, str]], None]


__all__ = ["CopyTarget", "_PendingForm", "_PendingInput", "_View"]
