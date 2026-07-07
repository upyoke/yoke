"""PostToolUse hook: nudge the field-note channel after a non-zero Yoke-CLI exit.

When a Bash invocation of a Yoke CLI surface exits non-zero, emit a
``hookSpecificOutput.additionalContext`` advisory carrying the canonical
field-note footer (``yoke_contracts.field_note_text.FOOTER``).
The advisory teaches the agent — at the exact moment a recipe gap surfaced
— to log the gap through ``yoke ouroboros field-note append`` before
retrying or moving on.

Heuristic for "this was a Yoke CLI invocation" is intentionally precise:

* Bash commands whose **first non-prefix token** is the installed ``yoke``
  binary (``yoke <subcommand>``); OR
* Bash commands containing a Yoke command-module prefix
  (``python3 -m yoke_core.cli.``, ``python3 -m yoke_core.api.``, or
  the transitional ``python3 -m runtime.api.`` shape).

Both anchors exclude unrelated ``python3`` invocations and arbitrary user
commands — false positives produce wasted advisory noise. Leading env-var
assignments (``FOO=bar python3 -m ...``) are skipped so the heuristic
matches the canonical recipe shape.

Failure posture is fail-open: empty stdin, malformed JSON, a non-Bash tool,
a zero exit, or any field-shape miss exits zero without emitting
``additionalContext`` so a hint defect cannot block tool use. The hook is
path-string parsing only — no DB, no IO — so latency is bounded by JSON
parse + regex extraction (target: <10ms p99).
"""

from __future__ import annotations

import json
import re
import shlex
import sys
from typing import Optional

from yoke_contracts.field_note_text import FOOTER
from runtime.harness.hook_runner.types import HookContext, HookDecision, Next, Outcome


TARGET_TOOL = "Bash"

# Anchors a Yoke CLI invocation. Substring presence is sufficient for the
# ``python3 -m <Yoke command module>.`` form (the prefixes are unambiguous);
# the bare
# ``yoke`` installed-binary form requires structural token analysis
# (skip env-var assignments, then check the first non-assignment token).
_PY_MODULE_PREFIXES = (
    "python3 -m yoke_core.cli.",
    "python3 -m yoke_core.api.",
    "python3 -m runtime.api.",
)
_YOKE_BINARY = "yoke"
_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_EXIT_CODE_RE = re.compile(r"Exit code (\d+)")


__all__ = [
    "FOOTER",
    "TARGET_TOOL",
    "build_advisory",
    "evaluate",
    "evaluate_fields",
    "is_yoke_cli_command",
    "main",
    "parse_exit_code",
]


def is_yoke_cli_command(command: str) -> bool:
    """Return True when ``command`` invokes a Yoke CLI surface.

    Matches either a Yoke ``python3 -m`` command-module invocation anywhere
    in the command (covers chained invocations and pipelines), or the installed
    ``yoke`` binary as the first non-env-assignment token of any
    ``;``/``&&``/``||``/``|``-separated clause. Returns False for any
    unrelated command shape (``git status``, ``ls``, arbitrary
    ``python3 script.py`` calls, etc.).
    """
    if not command or not isinstance(command, str):
        return False
    if any(prefix in command for prefix in _PY_MODULE_PREFIXES):
        return True
    # Split into clauses on shell separators so a leading clause's `yoke`
    # is detected even when followed by pipes or chains. shlex.split tokenises
    # each clause; env-var assignments at the front are skipped.
    for clause in re.split(r"[|&;]+", command):
        stripped = clause.strip()
        if not stripped:
            continue
        try:
            tokens = shlex.split(stripped, posix=True)
        except ValueError:
            # Unbalanced quotes — fall back to whitespace split.
            tokens = stripped.split()
        idx = 0
        while idx < len(tokens) and _ENV_ASSIGN_RE.match(tokens[idx]):
            idx += 1
        if idx >= len(tokens):
            continue
        if tokens[idx] == _YOKE_BINARY:
            return True
    return False


def parse_exit_code(response: object) -> Optional[int]:
    """Extract the integer exit code from a PostToolUse ``tool_response`` field.

    Returns the exit code on a successful parse, or ``None`` when the
    response carries no recognisable ``Exit code N`` text. Treats the
    ``content`` list-of-blocks shape and bare-string shapes identically.
    """
    text: str
    if isinstance(response, dict):
        content = response.get("content", "")
        if isinstance(content, list):
            text = " ".join(
                str(c.get("text", "")) if isinstance(c, dict) else str(c)
                for c in content
            )
        elif isinstance(content, str):
            text = content
        else:
            text = str(content)
    elif isinstance(response, str):
        text = response
    else:
        return None
    match = _EXIT_CODE_RE.search(text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def build_advisory(command: str, exit_code: int) -> str:
    """Return the ``additionalContext`` advisory body for a non-zero Yoke exit.

    The body opens with a one-line situation report so the agent can match
    the advisory to the failing command, then carries the canonical
    ``FOOTER`` verbatim so every surface (denial messages, recovery hints,
    this hook) renders byte-identical field-note teaching.
    """
    head = command.strip().splitlines()[0] if command else ""
    if len(head) > 200:
        head = head[:197] + "..."
    return (
        "<system-reminder>\n"
        f"Yoke CLI exited non-zero (exit_code={exit_code}): `{head}`\n"
        "\n"
        f"{FOOTER}\n"
        "</system-reminder>"
    )


def evaluate_fields(
    command: str,
    exit_code: Optional[int],
) -> Optional[str]:
    """Pure decision helper. Returns the advisory body or ``None``."""
    if exit_code is None or exit_code == 0:
        return None
    if not is_yoke_cli_command(command):
        return None
    return build_advisory(command, exit_code)


def evaluate(record: HookContext) -> HookDecision:
    """Typed entry. Returns NOOP + ``additionalContext`` on non-zero Yoke exit.

    Any payload-shape miss, non-Bash tool, or zero exit short-circuits to
    a plain NOOP so the hint never blocks tool use.
    """
    payload = record.payload if isinstance(record.payload, dict) else {}
    tool = record.tool_name or payload.get("tool_name")
    if tool != TARGET_TOOL:
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    command = tool_input.get("command", "") or ""
    if not isinstance(command, str):
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    exit_code = parse_exit_code(payload.get("tool_response"))
    advisory = evaluate_fields(command, exit_code)
    if advisory is None:
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    return HookDecision(
        outcome=Outcome.NOOP,
        audit_fields={"additionalContext": advisory},
        next=Next.CONTINUE,
    )


def _build_context_from_payload(payload: dict) -> HookContext:
    tool = payload.get("tool_name")
    sid = payload.get("session_id")
    cwd = payload.get("cwd")
    return HookContext(
        event_name="PostToolUse",
        executor_family="claude",
        executor_surface="claude",
        payload=payload,
        tool_name=tool if isinstance(tool, str) else None,
        cwd=cwd if isinstance(cwd, str) else None,
        session_id=sid if isinstance(sid, str) else None,
    )


def main() -> int:
    """CLI entry: stdin -> evaluate -> emit hookSpecificOutput envelope."""
    try:
        stdin_data = sys.stdin.read()
    except Exception:
        return 0
    if not stdin_data or not stdin_data.strip():
        return 0
    try:
        payload = json.loads(stdin_data)
    except json.JSONDecodeError:
        return 0
    if not isinstance(payload, dict):
        return 0
    try:
        decision = evaluate(_build_context_from_payload(payload))
    except Exception:
        # Crash isolation: any internal failure exits zero so the hook
        # never blocks tool use. observe(_post) downstream still records the
        # actual tool call.
        return 0
    additional = decision.audit_fields.get("additionalContext")
    if not additional:
        return 0
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": additional,
        }
    }))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI shim
    raise SystemExit(main())
