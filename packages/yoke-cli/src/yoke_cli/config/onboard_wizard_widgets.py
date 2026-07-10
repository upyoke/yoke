"""Reusable widgets for the full-screen ``yoke onboard`` wizard.

The stepper and the arrow-key selection list are presentation-only; they hold
no onboarding logic. They render the wizard's phase model and the per-step
option rows that the screens in :mod:`onboard_wizard` collect into the field
set :func:`yoke_cli.config.onboard.build_report` consumes. All color lives in
``onboard_wizard.tcss``; these widgets only toggle classes and emit messages.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Input, Static

from yoke_cli.config.onboard_terminal import glyphs, plain_glyphs, plain_text
from yoke_cli.config.onboard_wizard_step_ids import (
    STEP_CONNECT,
    STEP_FINISH,
    STEP_GITHUB,
    STEP_INSTALL,
    STEP_PROJECT,
)

# Default label for the one destination-dependent rail segment: hosted and
# team-server runs sign in to an account there; a local run sets up the
# machine's own universe instead (the app overrides ``Stepper.account_label``).
STEP_CONNECT_LABEL = "Account"

# Header reads Install -> Account -> GitHub -> Project -> Review; the stepper
# renders in this order regardless of which screen is active. Labels are nouns
# (the subject of each step) for a consistent rail: Account = your Yoke
# account (or the local universe, per the destination picker), Review = the
# write-plan review. PATH setup folds into Install (its screens highlight the
# Install segment) so the installer hand-off and onboarding read as one
# continuous app; GitHub precedes Project so App authorization is connected
# before the project step that reuses it.
STEPPER_ORDER = (
    (STEP_INSTALL, "Install"),
    (STEP_CONNECT, STEP_CONNECT_LABEL),
    (STEP_GITHUB, "GitHub"),
    (STEP_PROJECT, "Project"),
    (STEP_FINISH, "Review"),
)


@dataclass(frozen=True)
class SelectionRow:
    """One arrow-key option: a stable value, a label, and a dim right hint."""

    value: str
    label: str
    hint: str


class Stepper(Static):
    """Fixed four-step progress rail driven by the active step id.

    The wizard's ordered phases double as the stepper model; ``active`` names
    the current phase and every earlier phase renders as completed.
    """

    active: reactive[str] = reactive(STEP_CONNECT)
    # The Account segment's label follows the chosen deployment destination
    # (sign-in destinations keep the default; a local run reads as universe
    # setup). The app assigns it alongside ``active`` on every body swap.
    account_label: reactive[str] = reactive(STEP_CONNECT_LABEL)

    def render(self) -> Text:
        active_index = _step_index(self.active)
        marks = glyphs()
        line = Text()
        for index, (step_id, label) in enumerate(STEPPER_ORDER):
            if step_id == STEP_CONNECT:
                label = self.account_label
            if index:
                line.append(f" {marks.step_connector} ", style="#6e7681")
            if index < active_index:
                line.append(f"{marks.step_done} {label}", style="bold #3fb950")
            elif index == active_index:
                line.append(f"{marks.step_active} {label}", style="bold #56d364")
            else:
                line.append(f"{marks.step_pending} {label}", style="#6e7681")
        return line


class _OptionRow(Static):
    """A single selectable line: marker + label + right-aligned dim hint."""

    def __init__(self, row: SelectionRow) -> None:
        super().__init__()
        self._row = row

    def render(self) -> Text:
        selected = self.has_class("-selected")
        marks = glyphs()
        marker = marks.selected if selected else marks.unselected
        width = max(self.size.width, 40)
        prefix = f"{marker}  "
        label = plain_text(self._row.label) if plain_glyphs() else self._row.label
        hint = plain_text(self._row.hint) if plain_glyphs() else self._row.hint
        gap = max(width - len(prefix) - len(label) - len(hint), 1)
        line = Text()
        line.append(prefix)
        line.append(label)
        line.append(" " * gap)
        line.append(hint, style="dim" if not selected else "")
        return line


class SelectionList(Vertical, can_focus=True):
    """Arrow-key list with a marker, a label, and a right-aligned dim hint.

    Up/Down move the cursor; Enter emits :class:`Selected`. The selected row
    carries the caret marker, a green left-border bar, a tinted full-width
    background, and a bright label — all via the ``-selected`` class in the
    stylesheet; unselected rows stay dim.
    """

    cursor: reactive[int] = reactive(0)

    class Selected(Message):
        def __init__(self, value: str) -> None:
            self.value = value
            super().__init__()

    BINDINGS = [
        ("up", "cursor_up", "up"),
        ("down", "cursor_down", "down"),
        ("enter", "choose", "select"),
        ("ctrl+j", "choose", "select"),
        ("space", "choose", "select"),
    ]

    def __init__(self, rows: list[SelectionRow], *, initial: int = 0) -> None:
        super().__init__()
        self._rows = rows
        self.cursor = max(0, min(initial, len(rows) - 1)) if rows else 0

    def compose(self) -> ComposeResult:
        for row in self._rows:
            yield _OptionRow(row)

    def on_mount(self) -> None:
        self._sync_selection()

    @property
    def rows(self) -> list[SelectionRow]:
        return self._rows

    @property
    def selected_value(self) -> str:
        return self._rows[self.cursor].value

    def watch_cursor(self) -> None:
        if self.is_mounted:
            self._sync_selection()

    def action_cursor_up(self) -> None:
        if self._rows:
            self.cursor = (self.cursor - 1) % len(self._rows)

    def action_cursor_down(self) -> None:
        if self._rows:
            self.cursor = (self.cursor + 1) % len(self._rows)

    def action_choose(self) -> None:
        if self._rows:
            self.post_message(self.Selected(self.selected_value))

    def _sync_selection(self) -> None:
        for index, option in enumerate(self.query(_OptionRow)):
            option.set_class(index == self.cursor, "-selected")


def _step_index(step_id: str) -> int:
    for index, (candidate, _label) in enumerate(STEPPER_ORDER):
        if candidate == step_id:
            return index
    return 0


class FocusInput(Input):
    """Input that claims focus inside its own mount turn.

    Focus driven externally after mount (a post-mount ``set_focus``) leaves a
    window where a key the App forwards has no settled target and is dropped —
    the leading ``~`` of a typed path on a selection->input screen swap. Taking
    focus during ``on_mount`` establishes it before the next key is forwarded,
    so the first keystroke after a screen swap always lands.
    """

    def on_mount(self) -> None:
        self.focus()
        self.cursor_position = len(self.value or "")


__all__ = [
    "FocusInput",
    "STEPPER_ORDER",
    "STEP_CONNECT",
    "STEP_CONNECT_LABEL",
    "STEP_FINISH",
    "STEP_GITHUB",
    "STEP_INSTALL",
    "STEP_PROJECT",
    "SelectionList",
    "SelectionRow",
    "Stepper",
]
