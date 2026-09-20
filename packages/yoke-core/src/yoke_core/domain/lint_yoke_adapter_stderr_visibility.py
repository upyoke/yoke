"""PreToolUse Bash lint: keep Yoke adapter output readable.

Registered adapters already return a non-zero status and a named recovery
when they refuse, and they print their answer whole. Two shapes throw that
away, so this one guard refuses both:

* Suppressing stderr, or merging it into stdout immediately before a
  parser/truncator, discards the diagnosis and can make a correct refusal
  look like silence or malformed JSON. That rule lives here and applies to
  the named mutating command paths below.
* Piping any ``yoke`` invocation into ``head`` or ``tail`` keeps a byte
  window and drops the rest, including a refusal past the window. That rule
  lives in :mod:`yoke_core.domain.lint_yoke_adapter_output_truncation`,
  which also owns the ``yoke``-stage parsing both rules share.

This guard is deliberately narrow. It scans only live quote-aware pipeline
stages and allows every command shape it cannot classify confidently;
``--help`` output and watcher/test commands stay out of scope. The
suppression token is audit-only and never unblocks a denial.
"""

from __future__ import annotations

import json
import os
import shlex
import sys
from typing import Optional, Tuple

from yoke_contracts.hook_runner.denial_identity import attach_check_id
from yoke_core.domain.lint_yoke_adapter_output_truncation import (
    TRUNCATORS,
    find_truncation_violation,
    stage_tokens,
    truncation_reason,
    yoke_args,
)
from yoke_core.domain.path_claim_bash_splitter import iter_pipeline_groups
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome
from yoke_core.domain.lint_command_extract import extract_command as _extract_command

CHECK_ID = "lint-yoke-adapter-stderr-visibility"
HOOK_NAME = CHECK_ID
SUPPRESSION_TOKEN = "# lint:no-yoke-adapter-stderr-visibility-check"

_ITEM_STRUCTURED_WRITES = frozenset(
    {"replace", "append-addendum", "section-upsert", "section-append"}
)
_ITEM_SECTION_WRITES = frozenset({"upsert", "delete"})
_LAUNCH_WRITES = frozenset({"create", "retry", "reconcile"})
_MESSAGE_ACKS = frozenset({"ack", "acknowledge"})


def _extract_tool_name(payload: dict) -> str:
    for key in ("tool_name", "toolName"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _read_mode(payload: object | None = None) -> str:
    from yoke_core.domain import lint_config

    return lint_config.resolve_mode_for_payload(
        "lint_yoke_adapter_stderr_visibility", payload
    )


def _mutating_adapter_label(stage: str) -> Optional[str]:
    args = yoke_args(stage)
    if not args or any(token in {"--help", "-h"} for token in args):
        return None
    path: tuple[str, ...] = ()
    if args[0] in {"say", "dash"}:
        path = (args[0],)
    elif args[:2] in (["items", "create"], ["items", "cancel"]):
        path = tuple(args[:2])
    elif (
        args[:2] == ["items", "structured-field"]
        and len(args) >= 3
        and args[2] in _ITEM_STRUCTURED_WRITES
    ):
        path = tuple(args[:3])
    elif (
        args[:2] == ["items", "section"]
        and len(args) >= 3
        and args[2] in _ITEM_SECTION_WRITES
    ):
        path = tuple(args[:3])
    elif len(args) >= 3 and args[0] == "claims" and args[2] in {"acquire", "release"}:
        path = tuple(args[:3])
    elif args[:2] == ["lifecycle", "transition"]:
        path = tuple(args[:2])
    elif (
        args[:2] == ["session-control", "launch"]
        and len(args) >= 3
        and args[2] in _LAUNCH_WRITES
    ):
        path = tuple(args[:3])
    elif args[:1] == ["messages"] and len(args) >= 2 and args[1] in _MESSAGE_ACKS:
        path = tuple(args[:2])
    elif args[:2] == ["messages", "send"]:
        path = tuple(args[:2])
    elif args[:2] == ["deployment-runs", "create"]:
        path = tuple(args[:2])
    return "yoke " + " ".join(path) if path else None


def _redirection_tokens(stage: str) -> list[str]:
    try:
        lexer = shlex.shlex(stage, posix=True, punctuation_chars="<>&")
        lexer.whitespace_split = True
        lexer.commenters = ""
        return list(lexer)
    except ValueError:
        return []


def _has_redirection(tokens: list[str], target: str) -> bool:
    """Match ``2>target`` / ``2>&target`` with either punctuation shape."""
    for index, token in enumerate(tokens):
        if token != "2":
            continue
        following = tokens[index + 1 : index + 4]
        if len(following) >= 2 and following[:2] in (
            [">", target],
            [">&", target],
        ):
            return True
        if len(following) >= 3 and following[:3] == [">", "&", target]:
            return True
    return False


def _is_parser_or_truncator(stage: str) -> bool:
    tokens = stage_tokens(stage)
    if not tokens:
        return False
    command = os.path.basename(tokens[0])
    if command in TRUNCATORS:
        return True
    return command in {"python", "python3"} and "-c" in tokens[1:]


def _find_violation(command: str) -> Optional[Tuple[str, str]]:
    for stages in iter_pipeline_groups(command):
        for index, stage in enumerate(stages):
            label = _mutating_adapter_label(stage)
            if label is None:
                continue
            redirects = _redirection_tokens(stage)
            if _has_redirection(redirects, "/dev/null"):
                return label, "suppressed stderr with `2>/dev/null`"
            if _has_redirection(redirects, "-"):
                return label, "closed stderr with `2>&-`"
            if _has_redirection(redirects, "1") and any(
                _is_parser_or_truncator(later) for later in stages[index + 1 :]
            ):
                return label, "merged stderr into parsed or truncated stdout"
    return None


def _format_reason(label: str, hazard: str, suppression_seen: bool, mode: str) -> str:
    body = (
        f"BLOCKED: state-changing Yoke adapter hid its diagnostic stderr "
        f"(`{label}` {hazard}).\n\n"
        "Registered adapters already emit a named refusal, recovery step, and "
        "non-zero status. Keep stderr visible so that diagnosis reaches the "
        "operator and harness.\n\n"
        "Run the adapter bare:\n"
        f"  {label} <arguments>\n\n"
        "If stdout must be parsed, pipe stdout only and leave stderr attached "
        "to the terminal:\n"
        f"  {label} <arguments> --json | python3 -c '<parse stdin>'\n\n"
        "Do not add `2>/dev/null`, `2>&-`, or `2>&1` before a parser, `tail`, "
        "or `head`."
    )
    if mode == "warn":
        body += "\n\n[mode=warn] this hook would block in deny mode."
    elif suppression_seen:
        body += (
            f"\n\nSuppression token `{SUPPRESSION_TOKEN}` is recorded as audit "
            "evidence (outcome=suppression_attempted) but does NOT unblock."
        )
    return attach_check_id(body, check_id=CHECK_ID)


def evaluate_payload(payload: dict) -> Optional[Tuple[str, str, str]]:
    if not isinstance(payload, dict):
        return None
    tool = _extract_tool_name(payload)
    if tool and tool != "Bash":
        return None
    command = _extract_command(payload)
    if not command:
        return None
    # A hidden refusal is the graver of the two shapes, so a command that
    # commits both is named by its stderr hazard rather than its truncator.
    hidden = _find_violation(command)
    truncated = None if hidden is not None else find_truncation_violation(command)
    if hidden is None and truncated is None:
        return None
    mode = _read_mode(payload)
    suppression_seen = SUPPRESSION_TOKEN in command
    if hidden is not None:
        reason = _format_reason(*hidden, suppression_seen, mode)
    else:
        reason = truncation_reason(
            *truncated,
            suppression_seen,
            mode,
            check_id=CHECK_ID,
            suppression_token=SUPPRESSION_TOKEN,
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
    verdict = evaluate_payload(payload)
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
    cwd, session_id = payload.get("cwd"), payload.get("session_id")
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
