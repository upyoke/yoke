"""PreToolUse hook: block structured-field transform shell choreography.

Catches the brittle pattern where an agent reads a structured item field
through ``items get`` (or equivalent), redirects the content to a temp
path or shell variable, transforms it with ad-hoc Python/sed/awk, and
pipes the result back into ``items update <field> --stdin`` or
``sections upsert --content-file``. The transform path hits
quoting/empty-content friction in practice and lacks idempotency; the
safe path is the helper at :mod:`yoke_core.domain.item_field_transform`.

Allowed shapes (the lint stays out of their way):

* direct ``items update <field> --stdin`` from a heredoc/printf with the
  full intended content,
* ``items update <field> --body-file <path>`` against a real artifact
  file,
* read-only ``items get`` calls,
* read-only ``sections get`` calls,
* invocations of the ``item_field_transform`` helper itself.

Bypass: add ``# lint:no-structured-transform-check`` to the command body.
Matching bypasses are allowed but emit ``outcome=suppression_attempted``
audit evidence (audit-only; the rule still denies).

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
from yoke_core.domain.lint_structured_field_transform_shell_messages import (
    REMEDIATION_API_FIRST,
    REMEDIATION_TEXT,
)
from runtime.harness.hook_runner.types import HookContext, HookDecision, Next, Outcome


_BYPASS_TOKEN = "# lint:no-structured-transform-check"

# ``items get <id> <structured-field>`` (router or service-client form);
# matches lines like ``db_router items get 42 spec`` or ``items get YOK-NN spec``.
_ITEMS_GET_RE = re.compile(
    r"\bitems\s+get\b[^\n;|&]*?\b"
    r"(spec|design_spec|technical_plan|worktree_plan|shepherd_log|"
    r"shepherd_caveats|test_results|deploy_log|browser_qa_metadata|"
    r"db_mutation_profile|db_compatibility_attestation)\b",
    re.IGNORECASE,
)

# ``items update <id> <field> --stdin`` is the structured-field stdin write.
_ITEMS_UPDATE_STDIN_RE = re.compile(
    r"\bitems\s+update\b[^\n;|&]*--stdin\b",
    re.IGNORECASE,
)

_SECTIONS_GET_RE = re.compile(
    r"\bsections\s+get\b[^\n;|&]*",
    re.IGNORECASE,
)

_SECTIONS_UPSERT_CONTENT_FILE_RE = re.compile(
    r"\bsections\s+upsert\b[^\n;|&]*--content-file\b",
    re.IGNORECASE,
)

# Indicators that the get output was redirected/captured for transform:
#   ``items get ... > /tmp/foo``
#   ``items get ... > $TMPDIR/foo``
#   ``_old=$(items get ...)``
#   ``items get ... | python3 -c '...'``
_GET_REDIRECT_PATTERNS = (
    re.compile(
        r"\bitems\s+get\b[^\n]*?(?:>|>>)\s*\S+",
        re.IGNORECASE,
    ),
    re.compile(
        r"=\s*\$\(\s*[^()]*?\bitems\s+get\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"=\s*`[^`]*?\bitems\s+get\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bitems\s+get\b[^\n]*?\|\s*(?:python3?|sed|awk|tr|perl)\b",
        re.IGNORECASE,
    ),
)

_SECTION_GET_REDIRECT_PATTERNS = (
    re.compile(
        r"\bsections\s+get\b[^\n]*?(?:>|>>)\s*\S+",
        re.IGNORECASE,
    ),
    re.compile(
        r"=\s*\$\(\s*[^()]*?\bsections\s+get\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"=\s*`[^`]*?\bsections\s+get\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bsections\s+get\b[^\n]*?\|\s*(?:python3?|sed|awk|tr|perl)\b",
        re.IGNORECASE,
    ),
)


def _extract_tool_input(payload: dict) -> dict:
    for key in ("tool_input", "toolInput", "input"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _extract_command(payload: dict) -> str:
    tool_input = _extract_tool_input(payload)
    command = tool_input.get("command")
    if isinstance(command, str) and command:
        return command
    cmd_alt = tool_input.get("cmd")
    if isinstance(cmd_alt, str) and cmd_alt:
        return cmd_alt
    top_cmd = payload.get("command")
    if isinstance(top_cmd, str) and top_cmd:
        return top_cmd
    return ""


def _is_helper_invocation(command: str) -> bool:
    """Allow direct invocations of the safe helper."""
    return "yoke_core.domain.item_field_transform" in command


def _command_has_get_redirect(command: str) -> bool:
    """``items get`` followed by a redirect / capture / pipe-to-transform."""
    for pattern in _GET_REDIRECT_PATTERNS:
        if pattern.search(command):
            return True
    return False


def _command_has_section_get_redirect(command: str) -> bool:
    """``sections get`` followed by redirect / capture / pipe-to-transform."""
    for pattern in _SECTION_GET_REDIRECT_PATTERNS:
        if pattern.search(command):
            return True
    return False


def _command_has_plain_get(command: str) -> bool:
    return bool(_ITEMS_GET_RE.search(command))


def _command_has_stdin_update(command: str) -> bool:
    return bool(_ITEMS_UPDATE_STDIN_RE.search(command))


def _command_has_plain_section_get(command: str) -> bool:
    return bool(_SECTIONS_GET_RE.search(command))


def _command_has_section_upsert(command: str) -> bool:
    return bool(_SECTIONS_UPSERT_CONTENT_FILE_RE.search(command))


def evaluate_command(command: str) -> Optional[str]:
    """Return a denial reason when *command* matches the choreography shape.

    Triggers only when the command captures existing structured content
    via redirect / command-substitution / pipe-to-transformer, then writes
    the transformed content back through ``items update <field> --stdin``
    or ``sections upsert --content-file``.

    Read-only ``items get`` and direct ``--stdin`` writes are allowed. The
    safe-helper invocation pattern is allowed unconditionally.
    """
    if not command:
        return None
    if _BYPASS_TOKEN in command:
        return None
    if _is_helper_invocation(command):
        return None
    has_structured_field_choreography = (
        _command_has_stdin_update(command)
        and _command_has_plain_get(command)
        and _command_has_get_redirect(command)
    )
    has_section_choreography = (
        _command_has_section_upsert(command)
        and _command_has_plain_section_get(command)
        and _command_has_section_get_redirect(command)
    )
    if not (has_structured_field_choreography or has_section_choreography):
        return None

    return REMEDIATION_TEXT + "\n\n" + REMEDIATION_API_FIRST


def evaluate_payload(payload: dict) -> Optional[str]:
    return evaluate_command(_extract_command(payload))


def _build_deny_response(reason: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
        "permissionDecision": "deny", "permissionDecisionReason": reason}}


def _emit_denial(payload: dict, reason: str, *, outcome: str = "denied") -> None:
    """Best-effort ``HarnessToolCallDenied`` audit event."""
    try:
        from runtime.harness.hook_runner.telemetry import emit_denial_event
    except Exception:
        return
    sid = payload.get("session_id") or ""
    tu = payload.get("tool_use_id") or ""
    turn = payload.get("turn_id") or payload.get("message_id") or ""
    try:
        emit_denial_event(
            hook="lint-structured-field-transform-shell", tool="Bash",
            check_id="structured_field_transform_choreography", reason=reason,
            session_id=sid if isinstance(sid, str) else "",
            tool_use_id=tu if isinstance(tu, str) else "",
            turn_id=turn if isinstance(turn, str) else "",
            command_snippet=_extract_command(payload), outcome=outcome)
    except Exception:
        pass


def evaluate(record: HookContext) -> HookDecision:
    """Typed entry. Wraps :func:`evaluate_payload` + bypass-token audit."""
    payload = record.payload if isinstance(record.payload, dict) else {}
    command = _extract_command(payload)
    if _BYPASS_TOKEN in command and not _is_helper_invocation(command):
        if evaluate_command(command.replace(_BYPASS_TOKEN, "")):
            _emit_denial(payload, ("[outcome=suppression_attempted] structured-field "
                "transform shell lint suppressed via token"),
                outcome="suppression_attempted")
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    reason = evaluate_command(command)
    if reason is None:
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    reason = append_field_note_footer(reason, rule_id="lint-structured-field-transform-shell")
    envelope = json.dumps(_build_deny_response(reason))
    _emit_denial(payload, reason)
    return HookDecision(outcome=Outcome.DENY, message=envelope,
        audit_fields={"reason": reason, "audit_outcome": "denied"},
        block=True, next=Next.STOP)


def _build_context_from_payload(payload: dict) -> HookContext:
    """Build a minimal :class:`HookContext` for the legacy stdin entry."""
    cwd, sid = payload.get("cwd"), payload.get("session_id")
    return HookContext(event_name="PreToolUse", executor_family="claude",
        executor_surface="claude", payload=payload, tool_name="Bash",
        command_body=_extract_command(payload) or None,
        cwd=cwd if isinstance(cwd, str) else None,
        session_id=sid if isinstance(sid, str) else None)


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


__all__ = [
    "evaluate",
    "evaluate_command",
    "evaluate_payload",
    "main",
]


if __name__ == "__main__":  # pragma: no cover - CLI shim
    sys.exit(main())
