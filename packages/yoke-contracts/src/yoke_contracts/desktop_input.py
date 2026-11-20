"""Shape and refusals of one desktop input action a QA walker sends a host."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

ACTIONS = ("windows", "focus", "click", "type", "keys", "read")
WINDOW_ACTIONS = frozenset(ACTIONS) - {"windows"}
ELEMENT_KEYS = ("name", "automation_id", "control_type")
MAX_TEXT_CHARACTERS = 4096
MAX_WAIT_SECONDS = 60

# Credential shapes refused even when the lease staged no matching secret.
_SECRET_SHAPES = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{32,}"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}"),
)
_WINDOW = ("title", "process", "handle")
_ELEMENT = (*ELEMENT_KEYS, "index")
_ACTION_OPTIONS = {
    "windows": (),
    "focus": _WINDOW,
    "click": (*_WINDOW, *_ELEMENT, "x", "y", "button", "double"),
    "type": (*_WINDOW, *_ELEMENT, "text"),
    "keys": (*_WINDOW, "keys"),
    "read": (*_WINDOW, *_ELEMENT),
}
_KEY_TOKEN = re.compile(r"^[A-Za-z0-9]+(?:\+[A-Za-z0-9]+)*$|^[^\s+]$")


@dataclass
class DesktopInputRefused(Exception):
    """A named refusal: the code, what was observed and the recovery step."""

    code: str
    detail: str
    recovery: str

    def __str__(self) -> str:
        return f"{self.code}: {self.detail}; recovery: {self.recovery}"


def _refuse(code: str, detail: str, recovery: str) -> DesktopInputRefused:
    return DesktopInputRefused(code, detail, recovery)


def refuse_secret_text(text: str, secrets: Sequence[str]) -> None:
    """Refuse text that carries a staged lease secret or a credential shape."""
    if any(secret and secret in text for secret in secrets) or any(
        shape.search(text) for shape in _SECRET_SHAPES
    ):
        raise _refuse(
            "desktop_input_secret_refused",
            "the text carries a secret or credential-shaped value",
            "Never type secrets through desktop input. Return WALK_STATUS: "
            "HUMAN_GATE naming the credential entry so a person enters it",
        )


def validate_request(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Return a normalized action request, or raise its named refusal."""
    action = raw.get("action")
    if action not in ACTIONS:
        raise _refuse(
            "desktop_input_action_invalid",
            f"unknown action {action!r}",
            "Use one of: " + ", ".join(ACTIONS),
        )
    unused = sorted(
        key
        for key, value in raw.items()
        if key not in ("action", "wait_seconds", *_ACTION_OPTIONS[action])
        and value not in (None, "", False)
    )
    if unused:
        raise _refuse(
            "desktop_input_option_unused",
            f"{action} does not use "
            + ", ".join("--" + key.replace("_", "-") for key in unused),
            "Remove those options; to click a point before typing, run `click` first",
        )
    request: dict[str, Any] = {"action": action}
    wait = int(raw.get("wait_seconds") or 0)
    if not 0 <= wait <= MAX_WAIT_SECONDS:
        raise _refuse(
            "desktop_input_wait_invalid",
            f"--wait-seconds {wait} is outside 0..{MAX_WAIT_SECONDS}",
            f"Pass --wait-seconds between 0 and {MAX_WAIT_SECONDS}",
        )
    request["wait_seconds"] = wait
    window = {
        key: str(raw[key])
        for key in ("title", "process", "handle")
        if raw.get(key) not in (None, "")
    }
    if action in WINDOW_ACTIONS and not window:
        raise _refuse(
            "desktop_input_window_required",
            f"{action} needs a target window",
            "Pass --title SUBSTRING, --process NAME or --handle HANDLE; "
            "list candidates with the `windows` action",
        )
    if "handle" in window and not re.fullmatch(r"(?:0x)?[0-9A-Fa-f]{1,16}", window["handle"]):
        raise _refuse(
            "desktop_input_handle_invalid",
            "--handle must be the hexadecimal handle the `windows` action printed",
            "Copy the handle from the `windows` action output",
        )
    request["window"] = window
    element = {
        key: str(raw[key]) for key in ELEMENT_KEYS if raw.get(key) not in (None, "")
    }
    if raw.get("index") is not None:
        if not element or int(raw["index"]) < 1:
            raise _refuse(
                "desktop_input_index_invalid",
                "--index needs an element selector and counts from 1",
                "Pass --index N with --name/--automation-id/--control-type, "
                "using the order a windows_element_ambiguous refusal listed",
            )
        element["index"] = str(int(raw["index"]))
    request["element"] = element
    if action == "read" and not set(element) & set(ELEMENT_KEYS):
        raise _refuse(
            "desktop_input_element_required",
            "read needs an element selector",
            "Pass --name, --automation-id or --control-type",
        )
    if action == "click":
        point = (raw.get("x"), raw.get("y"))
        if (point[0] is None) != (point[1] is None):
            raise _refuse(
                "desktop_input_point_incomplete",
                "click needs both --x and --y",
                "Pass both window-relative coordinates, or an element selector",
            )
        if (point[0] is None) == (not element):
            raise _refuse(
                "desktop_input_click_target_invalid",
                "click needs exactly one target: --x/--y or an element selector",
                "Pass window-relative --x/--y, or --name/--automation-id/--control-type",
            )
        if point[0] is not None:
            request["x"], request["y"] = int(point[0]), int(point[1])
            if request["x"] < 0 or request["y"] < 0:
                raise _refuse(
                    "desktop_input_point_invalid",
                    "window-relative coordinates must not be negative",
                    "Measure --x/--y from the window's top-left corner",
                )
        request["button"] = raw.get("button") or "left"
        if request["button"] not in ("left", "right"):
            raise _refuse(
                "desktop_input_button_invalid",
                f"unknown button {request['button']!r}",
                "Pass --button left or --button right",
            )
        request["double"] = bool(raw.get("double"))
    if action == "type":
        text = raw.get("text")
        if not isinstance(text, str) or not text:
            raise _refuse(
                "desktop_input_text_missing",
                "type read no text on stdin",
                "Pipe the text on stdin with --text-stdin",
            )
        if len(text) > MAX_TEXT_CHARACTERS:
            raise _refuse(
                "desktop_input_text_too_long",
                f"text has {len(text)} characters; the limit is {MAX_TEXT_CHARACTERS}",
                "Type the text in smaller parts",
            )
        if any(ord(c) < 32 or ord(c) == 127 for c in text):
            raise _refuse(
                "desktop_input_text_invalid",
                "text contains a newline, tab or other control character",
                "Type plain text only; send Enter, Tab and other keys with the `keys` action",
            )
        request["text"] = text
    if action == "keys":
        keys = str(raw.get("keys") or "").split()
        if not keys or not all(_KEY_TOKEN.match(chord) for chord in keys):
            raise _refuse(
                "desktop_input_keys_invalid",
                f"--keys {raw.get('keys')!r} is not a space-separated chord list",
                "Pass chords such as --keys 'ctrl+l' or --keys 'enter' or --keys 'ctrl+a backspace'",
            )
        request["keys"] = keys
    return request


__all__ = [
    "ACTIONS",
    "DesktopInputRefused",
    "MAX_TEXT_CHARACTERS",
    "MAX_WAIT_SECONDS",
    "refuse_secret_text",
    "validate_request",
]
