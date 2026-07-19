"""PreToolUse hook: Write tool path + content safety.

Python owner for ``.agents/skills/yoke/scripts/lint-write-path.sh``.

Two checks:

1. Block Write tool calls where ``file_path`` contains a literal ``$$``.
   The Write tool does not expand shell variables, so the file is created
   with ``$$`` in its name, while subsequent Bash commands expand ``$$``
   to the PID — causing "file not found" errors.

2. Block Write tool calls that write ``secrets.*`` in ``if:`` conditions
   of workflow YAML files. GitHub Actions silently fails to
   parse workflows with ``secrets.*`` in ``if:`` — the entire workflow
   shows zero jobs with no error message.

Typed entry: ``evaluate(record: HookContext) -> HookDecision``. The CLI
``__main__`` form (stdin -> payload -> HookContext -> evaluate) is
preserved for the registered shell hook; exit code is always ``0``.
"""

from __future__ import annotations

import json
import re
import sys
from typing import Optional

from yoke_core.domain.denial_field_note_footer import append_field_note_footer
from runtime.harness.hook_runner.types import HookContext, HookDecision, Next, Outcome


WORKFLOW_PATH_PATTERNS = (
    r"\.github/workflows/",
    r"projects/[^/]+/\.github/workflows/",
    r"projects/[^/]+/ops/",
)

_WORKFLOW_PATH_RE = re.compile("|".join(WORKFLOW_PATH_PATTERNS))


def _build_deny_response(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _extract_tool_input(payload: dict) -> dict:
    for key in ("tool_input", "toolInput", "input"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _is_workflow_yaml(file_path: str) -> bool:
    if not (file_path.endswith(".yml") or file_path.endswith(".yaml")):
        return False
    return bool(_WORKFLOW_PATH_RE.search(file_path))


def _scan_secrets_in_if(content: str) -> list[tuple[int, str]]:
    """Return a list of ``(line_number, stripped_line)`` violations.

    A violation is any line inside an ``if:`` expression (including a
    multi-line ``${{ ... }}`` expression) that references ``secrets.``.
    """
    violations: list[tuple[int, str]] = []
    in_multiline_if = False
    for idx, line in enumerate(content.split("\n"), start=1):
        if "if:" in line:
            if "secrets." in line:
                violations.append((idx, line.strip()))
            if "${" + "{" in line and "}" + "}" not in line:
                in_multiline_if = True
        elif in_multiline_if:
            if "secrets." in line:
                violations.append((idx, line.strip()))
            if "}" + "}" in line:
                in_multiline_if = False
    return violations


def _dollar_dollar_reason() -> str:
    return (
        "BLOCKED: Write file_path contains literal \"$$\".\n"
        "The Write tool does NOT expand shell variables — the file will be created\n"
        "with a literal \"$$\" in the name, but Bash will expand $$ to the PID,\n"
        "causing \"file not found\" errors.\n\n"
        "Fix: use mktemp in Bash first to get a concrete path, then Write to it:\n"
        "  _tmpfile=$(mktemp /tmp/my-prefix.XXXXXX)\n"
        "Then use the Write tool with file_path=\"$_tmpfile\".\n\n"
        "See AGENTS.md: \"Temp files\" rule."
    )


def _secrets_reason(file_path: str, violations: list[tuple[int, str]]) -> str:
    detail = "\n".join("  Line %d: %s" % (ln, txt) for ln, txt in violations)
    return (
        "BLOCKED: secrets.* in GitHub Actions if: condition.\n\n"
        "GitHub Actions silently fails to parse workflows when secrets.*\n"
        "appears in if: conditions — the entire workflow shows ZERO JOBS\n"
        "with no error message. This is a GitHub platform limitation.\n\n"
        "Violations found in %s:\n%s\n\n"
        "Fix: Pass secrets via env: and check the env var in run: instead:\n"
        "  # WRONG — silently breaks the entire workflow:\n"
        "  if: ${{ secrets.MY_SECRET != '' }}\n\n"
        "  # RIGHT — pass via env, check in run:\n"
        "  env:\n"
        "    MY_SECRET: ${{ secrets.MY_SECRET }}\n"
        "  run: |\n"
        "    if [ -z \"$MY_SECRET\" ]; then echo \"skipping\"; exit 0; fi"
    ) % (file_path, detail)


def evaluate_payload(payload: dict) -> Optional[str]:
    tool_input = _extract_tool_input(payload)
    file_path = tool_input.get("file_path", "")
    if not isinstance(file_path, str) or file_path == "":
        return None

    if "$$" in file_path:
        return _dollar_dollar_reason()

    if _is_workflow_yaml(file_path):
        content = tool_input.get("content", "")
        if isinstance(content, str) and "secrets." in content and "if:" in content:
            violations = _scan_secrets_in_if(content)
            if violations:
                return _secrets_reason(file_path, violations)

    return None


def _emit_denial(payload: dict, reason: str) -> None:
    try:
        from runtime.harness.hook_runner.telemetry import emit_denial_event
    except Exception:
        return
    session_id = payload.get("session_id") or ""
    tool_use_id = payload.get("tool_use_id") or ""
    turn_id = payload.get("turn_id") or payload.get("message_id") or ""
    tool_input = _extract_tool_input(payload)
    file_path = tool_input.get("file_path", "")
    command_snippet = file_path if isinstance(file_path, str) else ""
    try:
        emit_denial_event(
            hook="lint-write-path",
            tool="Write",
            check_id="lint-write-path",
            reason=reason,
            session_id=session_id if isinstance(session_id, str) else "",
            tool_use_id=tool_use_id if isinstance(tool_use_id, str) else "",
            turn_id=turn_id if isinstance(turn_id, str) else "",
            command_snippet=command_snippet,
        )
    except Exception:
        pass


def evaluate(record: HookContext) -> HookDecision:
    """Typed entry: evaluate Write payload for $$/secrets-in-if violations."""
    payload = record.payload if isinstance(record.payload, dict) else {}
    reason = evaluate_payload(payload)
    if reason is None:
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    reason = append_field_note_footer(reason, rule_id="lint-write-path")
    _emit_denial(payload, reason)
    envelope = json.dumps(_build_deny_response(reason))
    return HookDecision(
        outcome=Outcome.DENY,
        message=envelope,
        audit_fields={"reason": reason},
        block=True,
        next=Next.STOP,
    )


def _build_context_from_payload(payload: dict) -> HookContext:
    """Build a minimal :class:`HookContext` for the legacy stdin entry."""
    cwd, sid = payload.get("cwd"), payload.get("session_id")
    tool_input = _extract_tool_input(payload)
    file_path = tool_input.get("file_path")
    return HookContext(
        event_name="PreToolUse",
        executor_family="claude",
        executor_surface="claude",
        payload=payload,
        tool_name="Write",
        command_body=file_path if isinstance(file_path, str) else None,
        cwd=cwd if isinstance(cwd, str) else None,
        session_id=sid if isinstance(sid, str) else None,
    )


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
