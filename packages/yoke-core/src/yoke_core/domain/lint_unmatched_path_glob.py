"""PreToolUse Bash hook: refuse unquoted path globs that match no files.

zsh NOMATCH aborts the command before the tool runs when an unquoted path
glob such as ``docs/deploy*`` expands to nothing. Quoted patterns and
globs that do expand stay out of scope. The denial names ``rg --files``
as the enumeration alternative.
"""

from __future__ import annotations

import glob
import json
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from yoke_core.domain.denial_field_note_footer import append_field_note_footer
from yoke_core.domain.lint_session_cwd_target_extract import resolve_payload_cwd
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome

CHECK_ID = "lint-unmatched-path-glob"
HOOK_NAME = "lint-unmatched-path-glob"
SUPPRESSION_TOKEN = "# lint:no-unmatched-glob-check"

_GLOB_CHARS = frozenset("*?[")
_REDIR_PREFIXES = ("2>>", ">>", "&>", "2>", "1>", ">", "<")


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


def _extract_cwd(payload: dict, fallback: str = "") -> str:
    return resolve_payload_cwd(payload, fallback=fallback)


def _payload_cwd(payload: dict) -> str:
    cwd = payload.get("cwd")
    return cwd if isinstance(cwd, str) else ""


def _read_mode(payload: object | None = None) -> str:
    from yoke_core.domain import lint_config

    return lint_config.resolve_mode_for_payload(
        "lint_unmatched_path_glob",
        payload,
    )


def _unquoted_tokens(command: str) -> List[str]:
    tokens: List[str] = []
    current: List[str] = []
    in_single = in_double = escaped = False
    for char in command:
        if escaped:
            if not in_single and not in_double:
                current.append(char)
            escaped = False
            continue
        if char == "\\" and not in_single:
            escaped = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if in_single or in_double:
            continue
        if char.isspace() or char in ";|&":
            if current:
                tokens.append("".join(current))
                current = []
            continue
        current.append(char)
    if current:
        tokens.append("".join(current))
    return tokens


def _strip_redir(token: str) -> str:
    for prefix in _REDIR_PREFIXES:
        if token.startswith(prefix):
            return token[len(prefix) :]
    return token


def _unquoted_path_globs(command: str) -> List[str]:
    found: List[str] = []
    for token in _unquoted_tokens(command):
        path = _strip_redir(token)
        if "/" in path and any(char in path for char in _GLOB_CHARS):
            found.append(path)
    return found


def _glob_is_unmatched(cwd: str, token: str) -> bool:
    pattern = token if token.startswith("/") else str(Path(cwd) / token)
    try:
        return not glob.glob(pattern)
    except (OSError, ValueError):
        return False


def _find_unmatched(command: str, cwd: str) -> Optional[str]:
    if not cwd:
        return None
    for token in _unquoted_path_globs(command):
        if _glob_is_unmatched(cwd, token):
            return token
    return None


def _format_reason(
    token: str,
    suppression_seen: bool,
    mode: str,
    *,
    execution_cwd: str = "",
    payload_cwd: str = "",
) -> str:
    body = (
        "BLOCKED: unquoted path glob matches no files under the command cwd.\n\n"
        f"Detected: `{token}`\n"
    )
    if execution_cwd:
        body += f"Checked tree: `{execution_cwd}`\n"
    if payload_cwd and payload_cwd != execution_cwd:
        body += f"Payload cwd was `{payload_cwd}`.\n"
    body += (
        "\n"
        "zsh NOMATCH aborts the command before the tool runs. Enumerate "
        "candidates with `rg --files`, or quote a pattern the tool consumes:\n"
        "  rg --files | rg 'name-or-symbol'\n"
        "  rg --glob 'docs/deploy*' PATTERN\n\n"
        "Do not pass an optional unmatched path glob such as `docs/deploy*` "
        "directly to zsh."
    )
    if mode == "warn":
        body += "\n\n[mode=warn] this hook would block in deny mode."
    elif suppression_seen:
        body += (
            f"\n\nSuppression token `{SUPPRESSION_TOKEN}` is recorded as audit "
            "evidence (outcome=suppression_attempted) but does NOT unblock."
        )
    return append_field_note_footer(body, rule_id=CHECK_ID)


def evaluate_payload(
    payload: dict,
    *,
    fallback_cwd: str = "",
) -> Optional[Tuple[str, str, str]]:
    if not isinstance(payload, dict):
        return None
    tool = _extract_tool_name(payload)
    if tool and tool != "Bash":
        return None
    command = _extract_command(payload)
    if not command:
        return None
    execution_cwd = _extract_cwd(payload, fallback=fallback_cwd)
    token = _find_unmatched(command, execution_cwd)
    if token is None:
        return None
    suppression_seen = SUPPRESSION_TOKEN in command
    mode = _read_mode(payload)
    reason = _format_reason(
        token,
        suppression_seen,
        mode,
        execution_cwd=execution_cwd,
        payload_cwd=_payload_cwd(payload),
    )
    outcome = "suppression_attempted" if suppression_seen else "denied"
    return mode, reason, outcome


def _emit_audit_event(payload: dict, reason: str, mode: str, outcome: str) -> None:
    try:
        from yoke_core.hooks.telemetry import emit_denial_event
    except Exception:
        return
    try:
        emit_denial_event(
            hook=HOOK_NAME,
            tool="Bash",
            check_id=CHECK_ID,
            reason=f"[mode={mode}] {reason}" if mode == "warn" else reason,
            session_id=str(payload.get("session_id") or ""),
            tool_use_id=str(payload.get("tool_use_id") or ""),
            turn_id=str(payload.get("turn_id") or payload.get("message_id") or ""),
            command_snippet=_extract_command(payload),
            outcome=outcome,
        )
    except Exception:
        pass


def evaluate(record: HookContext) -> HookDecision:
    payload = record.payload if isinstance(record.payload, dict) else {}
    verdict = evaluate_payload(payload, fallback_cwd=record.cwd or "")
    if verdict is None:
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    mode, reason, outcome = verdict
    _emit_audit_event(payload, reason, mode, outcome)
    audit = {"mode": mode, "reason": reason, "audit_outcome": outcome}
    if mode == "deny":
        envelope = json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
        return HookDecision(
            outcome=Outcome.DENY,
            message=envelope,
            audit_fields=audit,
            block=True,
            next=Next.STOP,
        )
    return HookDecision(outcome=Outcome.WARN, message="", audit_fields=audit)


def _build_context_from_payload(payload: dict) -> HookContext:
    cwd = payload.get("cwd")
    session_id = payload.get("session_id")
    return HookContext(
        event_name="PreToolUse",
        executor_family="claude",
        executor_surface="claude",
        payload=payload,
        tool_name=_extract_tool_name(payload) or None,
        command_body=_extract_command(payload) or None,
        cwd=cwd if isinstance(cwd, str) else None,
        session_id=session_id if isinstance(session_id, str) else None,
    )


def main() -> int:
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
