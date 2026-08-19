"""PreToolUse Bash hook: steer full-suite pytest runs into the wrapper.

Machine-wide admission (:mod:`yoke_core.tools.gate_admission`) caps how
many heavy test gates execute at once, and every path that goes through
``watch_pytest`` or ``run_tests`` arbitrates for that slot. A bare
``python3 -m pytest <dirs>`` does not: it spawns its own xdist worker
fleet and its own database fan-out while holding nothing, so it is
invisible to every other run on the machine. Five concurrent suites were
observed live on one host that way.

Two verdicts, because two shapes carry different certainty:

- A run naming the project's whole verification surface — every declared
  full-sweep anchor — is unambiguously the heavy gate and is DENIED with
  the wrapper spelling.
- Any other directory-shaped sweep is heavy enough to matter but may be a
  deliberate narrow investigation, so it WARNs and names the wrapper.

File-scoped runs (``pytest path/to/test_x.py``, ``-k`` selections against
files) are cheap on every axis and are not matched at all — iterating on
one failing test must stay frictionless.

Pattern mirrors :mod:`yoke_core.domain.lint_pipe_to_truncator`: typed
``evaluate(record: HookContext) -> HookDecision`` entry, CLI ``__main__``
form for the legacy stdin invocation, mode resolved via the lint-config
registry, suppression token audit-only (does NOT unblock in deny mode).
"""

from __future__ import annotations

import json
import re
import sys
from typing import List, Optional, Sequence, Tuple

from yoke_contracts.watch_cli_forms import WATCH_CLI_TOKENS, cli_form
from yoke_core.domain.denial_field_note_footer import append_field_note_footer
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome

CHECK_ID = "lint-raw-pytest-full-suite"
HOOK_NAME = "lint-raw-pytest-full-suite"
SUPPRESSION_TOKEN = "# lint:no-raw-pytest-check"

#: Spellings that already arbitrate for the machine-wide admission slot.
#: A command mentioning any of these is running through an admitted path.
_ADMITTED_INVOCATIONS = (
    "yoke_core.tools.watch_pytest",
    "yoke_core.tools.run_tests",
    "yoke qa case run",
    *(cli_form(module) for module in WATCH_CLI_TOKENS),
)

#: Command separators that end one invocation.
_SEGMENT_SPLIT = re.compile(r"(?:;|&&|\|\||\||\n)")

#: Words that may precede the actual program in a pipeline stage.
_LAUNCHER_TOKENS = frozenset({
    "uv", "run", "env", "nice", "time", "command", "exec",
    "poetry", "hatch", "pdm", "rye",
})

#: Flags that take a separate value; their operand is not a path.
_VALUE_FLAGS = frozenset({
    "-k", "-m", "-n", "--numprocesses", "-p", "--dist", "--splits", "--group",
    "--splitting-algorithm", "--durations-path", "--durations", "--junitxml",
    "--tb", "--maxfail", "-c", "--rootdir", "--deselect", "--ignore",
})


def _extract_command(payload: dict) -> str:
    for key in ("tool_input", "toolInput", "input"):
        tool_input = payload.get(key)
        if isinstance(tool_input, dict):
            for command_key in ("command", "cmd"):
                value = tool_input.get(command_key)
                if isinstance(value, str) and value:
                    return value
    value = payload.get("command")
    return value if isinstance(value, str) else ""


def _extract_tool_name(payload: dict) -> str:
    for key in ("tool_name", "toolName"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _read_mode(payload: object | None = None) -> str:
    from yoke_core.domain import lint_config

    return lint_config.resolve_mode_for_payload(
        "lint_raw_pytest_full_suite", payload,
    )


def full_sweep_anchors() -> tuple[str, ...]:
    """Return the project's declared full-sweep anchor paths.

    Read from the same constant the impacted selector widens to, so what
    this guard calls "the whole suite" cannot drift from what the rest of
    the test tooling means by it. An unreadable constant degrades this
    guard to its advisory half rather than guessing a deny set.
    """
    try:
        from yoke_core.tools._impacted_import_index import TEST_ANCHORS

        return tuple(str(anchor).strip("/") for anchor in TEST_ANCHORS if anchor)
    except Exception:
        return ()


def _pytest_paths(tokens: Sequence[str]) -> List[str]:
    """Return the positional path operands of a pytest invocation."""
    paths: List[str] = []
    skip_next = False
    for token in tokens:
        if skip_next:
            skip_next = False
            continue
        if token in _VALUE_FLAGS:
            skip_next = True
            continue
        if token.startswith("-"):
            continue
        paths.append(token.split("::", 1)[0].strip("/"))
    return paths


def _pytest_tokens(segment: str) -> Optional[List[str]]:
    """Return the arguments of a raw pytest invocation in *segment*.

    The program is rarely the first word: environment assignments and
    launchers (``uv run --frozen``, ``env``, ``nice``) sit in front of it,
    and missing them is how a guard silently stops matching the spelling
    people actually type.
    """
    tokens = [token.lstrip("({") for token in segment.split() if token]
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.startswith("-"):
            index += 1
            continue
        if "=" in token or token.rsplit("/", 1)[-1] in _LAUNCHER_TOKENS:
            index += 1
            continue
        break
    if index >= len(tokens):
        return None
    program = tokens[index].rsplit("/", 1)[-1]
    rest = tokens[index + 1:]
    if program == "pytest":
        return rest
    if program.startswith("python"):
        for offset, token in enumerate(rest[:-1]):
            if token == "-m" and rest[offset + 1] == "pytest":
                return rest[offset + 2:]
    return None


def _classify(command: str) -> Optional[Tuple[str, str]]:
    """Return ``(severity, detail)`` for a raw sweep, else ``None``.

    ``severity`` is ``"full"`` for a run covering every declared anchor
    and ``"sweep"`` for any other directory-shaped run.
    """
    if any(marker in command for marker in _ADMITTED_INVOCATIONS):
        return None
    anchors = full_sweep_anchors()
    for segment in _SEGMENT_SPLIT.split(command):
        tokens = _pytest_tokens(segment)
        if tokens is None:
            continue
        paths = _pytest_paths(tokens)
        if anchors and set(anchors).issubset(set(paths)):
            return ("full", " ".join(anchors))
        directories = [path for path in paths if not path.endswith(".py")]
        if not paths:
            # No path operands at all: pytest sweeps its whole rootdir.
            return ("sweep", "the whole rootdir")
        if directories:
            return ("sweep", " ".join(directories))
    return None


def _format_reason(
    severity: str, detail: str, suppression_seen: bool, mode: str,
) -> str:
    verb = "BLOCKED" if severity == "full" else "HEAVY"
    body = (
        f"{verb}: raw pytest sweep over {detail}.\n\n"
        "A bare pytest invocation does not take the machine-wide test-gate\n"
        "admission slot, so it spawns a full xdist worker fleet and its own\n"
        "database fan-out alongside every other suite on this machine — and\n"
        "stays invisible to the runs that DO queue politely.\n\n"
        "Run it through the wrapper, which arbitrates for the slot and\n"
        "captures its own output:\n"
        "  yoke watch pytest --impacted main --bounded   # iteration default\n"
        "  yoke watch pytest -- <paths>                  # narrower scope\n"
        "To enumerate one CI shard without running its tests:\n"
        "  yoke watch pytest -- <CI shard args> --collect-only -q\n"
        "The item's blocking gate is its QA case run, not a hand-run sweep:\n"
        "  yoke qa case run --requirement-id <id>\n"
        "Doctrine: AGENTS.md `## Testing`"
    )
    if mode == "warn" or severity != "full":
        body += "\n\n[advisory] narrow, deliberate sweeps are legitimate."
    elif suppression_seen:
        body += (
            f"\n\nSuppression token `{SUPPRESSION_TOKEN}` is recorded as audit "
            "evidence (outcome=suppression_attempted) but does NOT unblock — "
            "the rule still denies. Use the wrapper spelling and retry."
        )
    return append_field_note_footer(body, rule_id=CHECK_ID)


def evaluate_payload(payload: dict) -> Optional[Tuple[str, str, str]]:
    """Apply the rule; return ``(mode, reason, outcome)`` when denying/warning."""
    if not isinstance(payload, dict):
        return None
    tool = _extract_tool_name(payload)
    if tool and tool != "Bash":
        return None
    command = _extract_command(payload)
    if not command:
        return None
    hit = _classify(command)
    if hit is None:
        return None
    severity, detail = hit
    suppression_seen = SUPPRESSION_TOKEN in command
    # Only the whole-surface shape is unambiguous enough to deny; a
    # narrower sweep advises regardless of the configured mode.
    mode = _read_mode(payload) if severity == "full" else "warn"
    reason = _format_reason(severity, detail, suppression_seen, mode)
    outcome = "suppression_attempted" if suppression_seen else (
        "denied" if mode == "deny" else "warned"
    )
    return (mode, reason, outcome)


def _emit_audit_event(payload: dict, reason: str, mode: str, outcome: str) -> None:
    try:
        from yoke_core.hooks.telemetry import emit_denial_event
    except Exception:
        return
    session_id = payload.get("session_id") or ""
    tool_use_id = payload.get("tool_use_id") or ""
    turn = payload.get("turn_id") or payload.get("message_id") or ""
    audit_reason = f"[mode={mode}] {reason}" if mode == "warn" else reason
    try:
        emit_denial_event(
            hook=HOOK_NAME, tool="Bash", check_id=CHECK_ID, reason=audit_reason,
            session_id=session_id if isinstance(session_id, str) else "",
            tool_use_id=tool_use_id if isinstance(tool_use_id, str) else "",
            turn_id=turn if isinstance(turn, str) else "",
            command_snippet=_extract_command(payload), outcome=outcome)
    except Exception:
        pass


def evaluate(record: HookContext) -> HookDecision:
    """Typed entry — pure shape parse, no subprocess fan-out."""
    payload = record.payload if isinstance(record.payload, dict) else {}
    verdict = evaluate_payload(payload)
    if verdict is None:
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    mode, reason, outcome = verdict
    _emit_audit_event(payload, reason, mode, outcome)
    audit = {"mode": mode, "reason": reason, "audit_outcome": outcome}
    if mode == "deny":
        envelope = json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
            "permissionDecision": "deny", "permissionDecisionReason": reason}})
        return HookDecision(outcome=Outcome.DENY, message=envelope,
            audit_fields=audit, block=True, next=Next.STOP)
    return HookDecision(outcome=Outcome.WARN, message="", audit_fields=audit)


def _build_context_from_payload(payload: dict) -> HookContext:
    cwd, session_id = payload.get("cwd"), payload.get("session_id")
    return HookContext(event_name="PreToolUse", executor_family="claude",
        executor_surface="claude", payload=payload,
        tool_name=_extract_tool_name(payload) or None,
        command_body=_extract_command(payload) or None,
        cwd=cwd if isinstance(cwd, str) else None,
        session_id=session_id if isinstance(session_id, str) else None)


def main() -> int:
    """CLI entry: stdin -> evaluate -> print deny envelope when denied."""
    try:
        payload = json.loads(sys.stdin.read() or "")
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    decision = evaluate(_build_context_from_payload(payload))
    if decision.outcome is Outcome.DENY and decision.message:
        print(decision.message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
