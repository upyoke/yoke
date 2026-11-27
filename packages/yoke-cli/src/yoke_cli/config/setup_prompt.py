"""The question every setup screen asks, as data both setup shells read.

The wizard renders a :class:`SetupPrompt` into widgets; agent mode prints it as
one JSON line and checks the agent's answer against it. Keeping the question,
its allowed answers and its validation in one place means a screen cannot show
the person one thing and accept another from an agent. This module imports no
Textual code so the agent path never depends on a terminal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

Validator = Callable[[str], "str | None"]

TONE_PLAIN = "plain"
TONE_OK = "ok"
TONE_ERROR = "error"

VALUE_REQUIRED = "A value is required."


@dataclass(frozen=True)
class SelectionRow:
    """One allowed answer: a stable value, a label, and a short hint."""

    value: str
    label: str
    hint: str


@dataclass(frozen=True)
class SetupInput:
    """A typed answer: the box's placeholder, masking and validation."""

    placeholder: str
    password: bool = False
    allow_placeholder: bool = True
    validate: Validator | None = None
    initial_value: str = ""


@dataclass(frozen=True)
class SetupField:
    """One labelled box in a screen that collects several values at once.

    ``key`` names the value in the dict the screen hands to its form handler and
    seeds the widget ids, so a field's box and its inline error slot are
    addressable on their own. ``secret`` defaults to ``password``; a masked box
    that holds a file path rather than a secret says ``secret=False``.
    """

    key: str
    label: str
    placeholder: str
    password: bool = False
    validate: Validator | None = None
    initial_value: str = ""
    secret: bool | None = None

    @property
    def is_secret(self) -> bool:
        return self.password if self.secret is None else self.secret

    @property
    def input_id(self) -> str:
        return f"onboard-input-{self.key}"

    @property
    def error_id(self) -> str:
        return f"onboard-input-error-{self.key}"


@dataclass(frozen=True)
class SetupHuman:
    """A browser step with instructions, a link, an optional code and a wait.

    ``max_seconds`` and ``poll_interval_seconds`` bound the approval wait that
    follows. Agent mode returns these details for the agent to act on.
    """

    instructions: str
    url: str | None = None
    user_code: str | None = None
    max_seconds: float | None = None
    poll_interval_seconds: float | None = None


@dataclass(frozen=True)
class SetupPrompt:
    """One setup question.

    ``key`` is a stable dotted name (``project.mode``) that agent answers use;
    a form field answers as ``<key>.<field key>``. ``tone`` selects the
    verification layout (``ok`` or ``error``) for result screens. ``guidance``
    tells an agent how to choose; the wizard does not show it.
    """

    key: str
    step: str
    title: str
    subtitle: str | None = None
    message: str | None = None
    detail_lines: tuple[str, ...] = ()
    choices: tuple[SelectionRow, ...] = ()
    tone: str = TONE_PLAIN
    input: SetupInput | None = None
    fields: tuple[SetupField, ...] = ()
    human: SetupHuman | None = None
    guidance: str = ""
    initial: int = 0
    selected: str | None = None

    @property
    def answerable(self) -> bool:
        return bool(self.choices or self.input or self.fields)

    @property
    def secret(self) -> bool:
        if self.input is not None:
            return self.input.password
        return any(item.is_secret for item in self.fields)

    def field_named(self, key: str) -> SetupField | None:
        return next((item for item in self.fields if item.key == key), None)


def check_choice(prompt: SetupPrompt, value: str) -> str | None:
    """None when ``value`` is one of the prompt's answers, else the reason."""
    allowed = [row.value for row in prompt.choices]
    if value in allowed:
        return None
    return f"{value!r} is not an allowed answer; use one of: {', '.join(allowed)}"


def check_input(spec: SetupInput, value: str) -> tuple[str, str | None]:
    """Apply the wizard's entry rules: default, validation, then required."""
    text = value.strip()
    if not text and spec.allow_placeholder:
        text = spec.placeholder.strip()
    if spec.validate is not None:
        error = spec.validate(text)
        if error:
            return text, error
    if not text:
        return text, VALUE_REQUIRED
    return text, None


def check_field(spec: SetupField, value: str) -> tuple[str, str | None]:
    """A form field's value after its default, with any validation message."""
    text = value.strip() or spec.initial_value.strip()
    error = spec.validate(text) if spec.validate is not None else None
    if error is None and not text:
        error = VALUE_REQUIRED
    return text, error


__all__ = [
    "SelectionRow",
    "SetupField",
    "SetupHuman",
    "SetupInput",
    "SetupPrompt",
    "TONE_ERROR",
    "TONE_OK",
    "TONE_PLAIN",
    "VALUE_REQUIRED",
    "check_choice",
    "check_field",
    "check_input",
]
