"""Reusable widgets for the full-screen ``yoke onboard`` wizard.

The stepper and the arrow-key selection list are presentation-only; they hold
no onboarding logic. They render the wizard's phase model and the per-step
option rows that the screens in :mod:`onboard_wizard` collect into the field
set :func:`yoke_cli.config.onboard.build_report` consumes. All color lives in
``onboard_wizard.tcss``; these widgets only toggle classes and emit messages.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.cells import cell_len
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
    STEP_HOSTING,
    STEP_INSTALL,
    STEP_PROJECT,
)

# Default label for the one destination-dependent rail segment: hosted and
# team-server runs sign in to an account there; a local run sets up the
# machine's own universe instead (the app overrides ``Stepper.account_label``).
STEP_CONNECT_LABEL = "Account"

# Header reads Install -> Account -> GitHub -> Project -> Hosting -> Review;
# the stepper renders in this order regardless of which screen is active.
# Labels are nouns (the subject of each step) for a consistent rail: Account =
# your Yoke account (or the local universe, per the destination picker),
# Hosting = the project's deploy credential, Review = the write-plan review.
# PATH setup folds into Install (its screens highlight the Install segment) so
# the installer hand-off and onboarding read as one continuous app; GitHub
# precedes Project so App authorization is connected before the project step
# that reuses it, and Hosting follows Project because the credential is stored
# per project.
STEPPER_ORDER = (
    (STEP_INSTALL, "Install"),
    (STEP_CONNECT, STEP_CONNECT_LABEL),
    (STEP_GITHUB, "GitHub"),
    (STEP_PROJECT, "Project"),
    (STEP_HOSTING, "Hosting"),
    (STEP_FINISH, "Review"),
)


@dataclass(frozen=True)
class SelectionRow:
    """One arrow-key option: a stable value, a label, and a dim right hint."""

    value: str
    label: str
    hint: str
    hint_on_new_line: bool = False


class Stepper(Static):
    """Fixed progress rail driven by the active step id.

    ``active`` names the current phase. Earlier phases render as completed
    except GitHub, which stays pending until the shell has proven the same
    ``ready`` contract as ``yoke github status``.
    """

    active: reactive[str] = reactive(STEP_CONNECT)
    # The Account segment's label follows the chosen deployment destination
    # (sign-in destinations keep the default; a local run reads as universe
    # setup). The app assigns it alongside ``active`` on every body swap.
    account_label: reactive[str] = reactive(STEP_CONNECT_LABEL)

    def render(self) -> Text:
        github_complete = _shell_github_complete(self)
        marks = glyphs()
        line = Text()
        for index, (step_id, label) in enumerate(STEPPER_ORDER):
            if step_id == STEP_CONNECT:
                label = self.account_label
            if index:
                line.append(f" {marks.step_connector} ", style="#6e7681")
            state = stepper_mark(
                step_id, active=self.active, github_complete=github_complete,
            )
            if state == "done":
                line.append(f"{marks.step_done} {label}", style="bold #3fb950")
            elif state == "active":
                line.append(f"{marks.step_active} {label}", style="bold #56d364")
            else:
                line.append(f"{marks.step_pending} {label}", style="#6e7681")
        return line


class _OptionRow(Static):
    """A single selectable line: marker + label + right-aligned dim hint."""

    def __init__(self, row: SelectionRow) -> None:
        super().__init__()
        self._row = row
        if row.hint_on_new_line:
            self.add_class("-hint-continuation")

    def render(self) -> Text:
        selected = self.has_class("-selected")
        width = max(self.size.width, 40)
        if self._row.hint_on_new_line:
            return _option_row_text(self._row, selected=selected, width=width)
        marks = glyphs()
        marker = marks.selected if selected else marks.unselected
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


def _option_row_text(row: SelectionRow, *, selected: bool, width: int) -> Text:
    """Keep an overflowing hint intact on a right-aligned continuation line."""
    marks = glyphs()
    marker = marks.selected if selected else marks.unselected
    prefix = f"{marker}  "
    label = plain_text(row.label) if plain_glyphs() else row.label
    hint = plain_text(row.hint) if plain_glyphs() else row.hint
    hint_style = "" if selected else "dim"
    line = Text()
    line.append(prefix)
    line.append(label)
    if not hint:
        return line
    if not row.hint_on_new_line:
        gap = max(width - len(prefix) - len(label) - len(hint), 1)
        line.append(" " * gap)
        line.append(hint, style=hint_style)
        return line
    line.append("\n")
    line.append(" " * max(width - cell_len(hint), 0))
    line.append(hint, style=hint_style)
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


def stepper_mark(
    step_id: str,
    *,
    active: str,
    github_complete: bool,
) -> str:
    """Return ``done``, ``active``, or ``pending`` for one rail segment."""

    active_index = _step_index(active)
    index = _step_index(step_id)
    if step_id == STEP_GITHUB and not github_complete:
        return "active" if index == active_index else "pending"
    if index < active_index:
        return "done"
    if index == active_index:
        return "active"
    return "pending"


def _shell_github_complete(widget: Static) -> bool:
    result = getattr(widget.app, "result", None)
    if result is None:
        return False
    from yoke_cli.config.onboard_wizard_github_state import connected

    return connected(result)


class FocusInput(Input):
    """Input that claims focus inside its own mount turn.

    Focus driven externally after mount (a post-mount ``set_focus``) leaves a
    window where a key the App forwards has no settled target and is dropped —
    the leading ``~`` of a typed path on a selection->input screen swap. Taking
    focus during ``on_mount`` establishes it before the next key is forwarded,
    so the first keystroke after a screen swap always lands.

    A screen that mounts several boxes wants that guarantee for the first field
    only: every later field passes ``claim_focus=False`` so the mount order does
    not decide where typing goes, and focus stays where the traversal rules put
    it.
    """

    def __init__(self, *args, claim_focus: bool = True, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._claim_focus = claim_focus

    def on_mount(self) -> None:
        if self._claim_focus:
            self.focus()
        self.cursor_position = len(self.value or "")


__all__ = [
    "FocusInput",
    "STEPPER_ORDER",
    "STEP_CONNECT",
    "STEP_CONNECT_LABEL",
    "STEP_FINISH",
    "STEP_GITHUB",
    "STEP_HOSTING",
    "STEP_INSTALL",
    "STEP_PROJECT",
    "SelectionList",
    "SelectionRow",
    "Stepper",
    "stepper_mark",
]
