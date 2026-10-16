"""Name a terminal recipe step that failed because its command already exited."""

from __future__ import annotations

import re
from typing import Any


_EXIT_MARKER = re.compile(r"^__YOKE_EXIT_([0-9]+)\s*$", re.MULTILINE)
_NAMED_REFUSAL = re.compile(r"^\W*[a-z][a-z0-9]*(?:_[a-z0-9]+)+: \S")


def marker_exit_code(transcript: str) -> int | None:
    """Return the last ``__YOKE_EXIT_<code>`` the terminal entry printed."""
    exits = _EXIT_MARKER.findall(transcript)
    return int(exits[-1]) if exits else None


def named_refusal(transcript: str) -> str | None:
    """Return the last ``code_name: reason`` line the command printed."""
    for line in reversed(transcript.splitlines()):
        if _NAMED_REFUSAL.match(line):
            return line.strip()
    return None


def step_failure(
    step: str,
    *,
    waiting_for: list[str],
    transcript: str,
    exit_code: int | None,
) -> tuple[str, dict[str, Any]]:
    """Return the error code and evidence for a step whose screen never came."""
    if exit_code is not None:
        refusal = named_refusal(transcript)
        return "terminal_setup_exited", {
            "step": step,
            "waiting_for": waiting_for,
            "setup_exit": {"exit_code": exit_code, "refusal": refusal},
            "recovery": (
                f"The command exited with code {exit_code} before step {step!r} "
                + (
                    f"after printing {refusal!r}"
                    if refusal
                    else "without a named refusal"
                )
                + "; repair that exit on the test machine, then rerun the case."
            ),
        }
    return "terminal_action_not_ready", {
        "step": step,
        "waiting_for": waiting_for,
        "recovery": (
            f"Step {step!r} never saw its ready text; update the recipe when the "
            "installer changed that prompt, or repair the application, then rerun."
        ),
    }


__all__ = ["marker_exit_code", "named_refusal", "step_failure"]
