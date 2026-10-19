"""The one JSON line agent-mode setup prints for each step event.

stdout carries exactly these lines, one object each; human progress and
designed-wait notices go to stderr. ``state`` is ``question``, ``browser``,
``done``, ``failed`` or ``refused``; the exit status follows the last line.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from typing import Any, TextIO

from rich.errors import MarkupError
from rich.text import Text

from yoke_cli.config.setup_prompt import SetupHuman, SetupPrompt

VERSION = 1
STATE_QUESTION = "question"
STATE_BROWSER = "browser"
STATE_DONE = "done"
STATE_FAILED = "failed"
STATE_REFUSED = "refused"
EXIT_CODES = {
    STATE_QUESTION: 0,
    STATE_BROWSER: 0,
    STATE_DONE: 0,
    STATE_FAILED: 1,
    STATE_REFUSED: 2,
}

SECRET_GUIDANCE = (
    "This answer is a secret, so setup never takes it through --answer. Take "
    "the non-secret route this question offers (a token file, or skipping the "
    "credential for now), or ask the person to finish this step in a terminal "
    "with `yoke setup --tui`."
)


def yoke_executable() -> str:
    """The running ``yoke`` by absolute path, so it works before PATH reloads."""
    argv0 = sys.argv[0] if sys.argv else ""
    if os.path.basename(argv0) == "yoke" and os.path.exists(argv0):
        return os.path.abspath(argv0)
    return shutil.which("yoke") or "yoke"


def answer_command(prompt: SetupPrompt) -> str:
    parts = [yoke_executable(), "setup", "--agent"]
    if prompt.input is not None or prompt.choices and not prompt.fields:
        parts.append(f"--answer {prompt.key}=<value>")
    else:
        parts.extend(
            f"--answer {prompt.key}.{field.key}=<value>"
            for field in prompt.fields
            if not field.is_secret
        )
        if prompt.choices:
            parts.append(f"--answer {prompt.key}={prompt.selected or '<value>'}")
    return " ".join(parts)


def human_data(human: SetupHuman | None) -> dict[str, Any] | None:
    if human is None:
        return None
    return {
        "instructions": plain(human.instructions),
        "url": human.url,
        "user_code": human.user_code,
    }


def wait_data(human: SetupHuman, *, silence_expected: bool = True) -> dict[str, Any]:
    return {
        "reason": "human_browser_approval",
        "max_seconds": human.max_seconds,
        "poll_interval_seconds": human.poll_interval_seconds,
        "silence_expected": silence_expected,
    }


def plain(text: str | None) -> str | None:
    """Screen copy without its Rich styling, as the person would read it."""
    if not text:
        return text
    try:
        return Text.from_markup(text).plain
    except MarkupError:
        return text


def question_fields(prompt: SetupPrompt) -> dict[str, Any]:
    detail = [text for text in (prompt.subtitle, prompt.message) if text]
    detail.extend(prompt.detail_lines)
    spec = prompt.input
    return {
        "step": prompt.step,
        "key": prompt.key,
        "question": plain(prompt.title),
        "detail": [plain(text) for text in detail],
        "answers": [
            {
                "value": row.value,
                "label": plain(row.label),
                "description": plain(row.hint),
            }
            for row in prompt.choices
        ],
        "input": None
        if spec is None
        else {
            "placeholder": spec.placeholder,
            "default": spec.placeholder
            if spec.allow_placeholder
            else spec.initial_value or None,
        },
        "fields": [
            {
                "key": f"{prompt.key}.{field.key}",
                "label": plain(field.label),
                "default": field.initial_value or None,
                "secret": field.is_secret,
            }
            for field in prompt.fields
        ],
        "secret": prompt.secret,
        "human": human_data(prompt.human),
        "guidance": _guidance(prompt),
        "answer_command": answer_command(prompt),
    }


def _guidance(prompt: SetupPrompt) -> str:
    if not prompt.secret:
        return prompt.guidance
    return " ".join(text for text in (prompt.guidance, SECRET_GUIDANCE) if text)


def response(state: str, **fields: Any) -> dict[str, Any]:
    return {"setup": "agent", "version": VERSION, "state": state, **fields}


def question(prompt: SetupPrompt) -> dict[str, Any]:
    return response(STATE_QUESTION, **question_fields(prompt))


def browser(step: str, key: str, human: SetupHuman) -> dict[str, Any]:
    return response(
        STATE_BROWSER,
        step=step,
        key=key,
        human=human_data(human),
        wait=wait_data(human),
        guidance=(
            "Show the person this link and any one-time code, and ask them to "
            "finish in their browser. Setup keeps waiting in this same command; "
            "do not run it again while it waits."
        ),
    )


def approval_pending(step: str, key: str, human: SetupHuman) -> dict[str, Any]:
    """Browser approval this call stopped at; the next call checks it once."""
    return response(
        STATE_BROWSER,
        step=step,
        key=key,
        human=human_data(human),
        wait=wait_data(human, silence_expected=False),
        answer_command=f"{yoke_executable()} setup --agent",
        guidance=(
            "Show the person this link and the match code and ask them to "
            "approve in their browser. This call has ended; when they say they "
            "are done, run answer_command. The same browser step again means "
            "approval is not finished yet. The code lapses after "
            "wait.max_seconds; setup then asks to start a fresh one. To choose "
            "another home instead, run `yoke setup --agent --discard` and "
            "start again."
        ),
    )


def refused(reason: str, recovery: str, prompt: SetupPrompt | None) -> dict[str, Any]:
    current = question_fields(prompt) if prompt is not None else {}
    return response(STATE_REFUSED, reason=reason, recovery=recovery, **current)


def failed(reason: str, recovery: str, **fields: Any) -> dict[str, Any]:
    return response(STATE_FAILED, reason=reason, recovery=recovery, **fields)


def interrupted(**fields: Any) -> dict[str, Any]:
    return failed(
        "setup_interrupted",
        "Setup was interrupted; completed changes and saved answers remain. "
        "Run `yoke setup --agent` again to continue from the last answered question.",
        **fields,
    )


def emit(payload: dict[str, Any], stream: TextIO | None = None) -> None:
    out = stream or sys.stdout
    out.write(json.dumps(payload, default=str) + "\n")
    out.flush()


__all__ = [
    "EXIT_CODES",
    "STATE_BROWSER",
    "STATE_DONE",
    "STATE_FAILED",
    "STATE_QUESTION",
    "STATE_REFUSED",
    "answer_command",
    "approval_pending",
    "browser",
    "emit",
    "failed",
    "plain",
    "question",
    "refused",
    "response",
    "yoke_executable",
]
