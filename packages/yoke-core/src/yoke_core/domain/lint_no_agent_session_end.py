"""PreToolUse Bash hook: refuse agent-context ``service_client session-end``.

The harness owns session lifetime — ``Stop`` and ``SessionEnd`` hooks route
through ``runtime/harness/hook_runner/session_end_cleanup.py`` and call
``service_client session-end --force --release-claims`` from a hook-runner
``subprocess.run`` (PreToolUse does NOT fire for hook-runner-internal
subprocess invocations, so this lint never sees those legitimate calls).

What this lint catches is the inverse: a Bash tool call dispatched by the
*agent* that shells out to ``service_client session-end`` /
``service_client session-end-if-empty``. Agents that want to surrender
their work without ending the session use the positive primitive:

    yoke claims work release --all-mine

Allowed shapes the lint stays out of:

* ``yoke claims work release --all-mine`` — the positive primitive.
* ``service_client claim-work --item YOK-N`` — unrelated subcommand.
* ``echo "to end the session, ..."`` — echo, not invocation.
* ``cat docs/session-end-events.md`` — docs path mention, not invocation.
* ``python3 -m yoke_core.api.service_client session-end-if-empty``
  invoked from inside the hook runner — PreToolUse never sees it.

Mode pinned by machine config key ``lint_agent_session_end_mode``. The
default is ``deny`` (Yoke dogfood). Suppression token
``# lint:no-agent-session-end-check`` is recorded as audit evidence only —
the rule still denies in ``deny`` mode.
"""

from __future__ import annotations

import json
import os
import shlex
import sys
from typing import Optional, Tuple

from yoke_core.domain.denial_field_note_footer import append_field_note_footer
from runtime.harness.hook_runner.types import HookContext, HookDecision, Next, Outcome

CHECK_ID = "lint-no-agent-session-end"
HOOK_NAME = "lint-no-agent-session-end"
SUPPRESSION_TOKEN = "# lint:no-agent-session-end-check"

_BANNED_SUBCOMMANDS = ("session-end", "session-end-if-empty")


def _extract_command(payload: dict) -> str:
    for k in ("tool_input", "toolInput", "input"):
        ti = payload.get(k)
        if isinstance(ti, dict):
            for ck in ("command", "cmd"):
                v = ti.get(ck)
                if isinstance(v, str) and v:
                    return v
    v = payload.get("command")
    return v if isinstance(v, str) else ""


def _extract_tool_name(payload: dict) -> str:
    for k in ("tool_name", "toolName"):
        v = payload.get(k)
        if isinstance(v, str) and v:
            return v
    return ""


def _read_mode(payload: object | None = None) -> str:
    # Single surface: resolve via the lint_config registry (.yoke/lint-config),
    # which applies the protected-guard clamp uniformly.
    from yoke_core.domain import lint_config

    return lint_config.resolve_mode_for_payload("lint_no_agent_session_end", payload)


def _is_service_client_token(tok: str) -> bool:
    """True when ``tok`` is the ``service_client`` module or script invocation.

    Matches both the ``python3 -m yoke_core.api.service_client`` shape (the
    token is ``yoke_core.api.service_client``) and the script-path shape
    (``runtime/api/service_client.py``).
    """
    base = os.path.basename(tok)
    if base in ("service_client", "service_client.py"):
        return True
    if tok.endswith(".service_client"):
        return True
    return False


def _command_invokes_banned_session_end(command: str) -> bool:
    """Return True when the command shells out to ``service_client session-end*``.

    Uses ``shlex.split`` to tokenize, then walks each ``service_client``
    invocation in the (potentially compound) command. Recognises the
    canonical ``python3 -m yoke_core.api.service_client session-end`` shape
    plus the legacy script-path form. Echoes, docs paths, and unrelated
    subcommands do not match.
    """
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return False
    n = len(tokens)
    for i, tok in enumerate(tokens):
        if not _is_service_client_token(tok):
            continue
        # Scan forward for the next non-flag positional within this clause;
        # stop at shell operators that terminate the current invocation.
        for j in range(i + 1, n):
            arg = tokens[j]
            if arg in (";", "&&", "||", "|", "&"):
                break
            if arg.startswith("-"):
                continue
            if arg in _BANNED_SUBCOMMANDS:
                return True
            # The first non-flag positional is the subcommand. Anything
            # else stops the search for this invocation.
            break
    return False


def _format_reason(suppression_seen: bool, mode: str) -> str:
    body = (
        "BLOCKED: `service_client session-end` (and "
        "`service_client session-end-if-empty`) are not the agent-facing "
        "shape for surrendering work.\n\n"
        "The harness owns session lifetime — Stop and SessionEnd hooks "
        "are the only legitimate callers and they invoke the helper from "
        "inside the hook runner (PreToolUse never fires for those "
        "subprocess invocations). Agents that want to surrender claims "
        "without ending the session use the positive primitive:\n\n"
        "  yoke claims work release --all-mine\n\n"
        "This releases every active claim THIS session still holds while "
        "leaving the session alive for the harness to terminate cleanly "
        "via its own hooks. The canonical release reason "
        "`agent_handoff_session_scoped` is recorded on each "
        "WorkReleased event and on the aggregate "
        "HarnessSessionEndReleasedClaims envelope.\n\n"
        "Doctrine: AGENTS.md `## Code Conventions` → Operational "
        "primitives. Skill prose, agent bodies, and dispatch context "
        "teach the release primitive; the harness owns the session."
    )
    if mode == "warn":
        body = body + "\n\n[mode=warn] this hook would block in deny mode."
    elif suppression_seen:
        body = (
            body
            + f"\n\nSuppression token `{SUPPRESSION_TOKEN}` is recorded "
              "as audit evidence (outcome=suppression_attempted) but does "
              "NOT unblock."
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
    if not _command_invokes_banned_session_end(command):
        return None
    suppression_seen = SUPPRESSION_TOKEN in command
    mode = _read_mode(payload)
    reason = _format_reason(suppression_seen, mode)
    outcome = "suppression_attempted" if suppression_seen else "denied"
    return (mode, reason, outcome)


def _emit_audit_event(
    payload: dict, reason: str, mode: str, outcome: str,
) -> None:
    try:
        from runtime.harness.hook_runner.telemetry import emit_denial_event
    except Exception:
        return
    sid = payload.get("session_id") or ""
    tu = payload.get("tool_use_id") or ""
    turn = payload.get("turn_id") or payload.get("message_id") or ""
    audit_reason = f"[mode={mode}] {reason}" if mode == "warn" else reason
    try:
        emit_denial_event(
            hook=HOOK_NAME, tool="Bash", check_id=CHECK_ID, reason=audit_reason,
            session_id=sid if isinstance(sid, str) else "",
            tool_use_id=tu if isinstance(tu, str) else "",
            turn_id=turn if isinstance(turn, str) else "",
            command_snippet=_extract_command(payload), outcome=outcome,
        )
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
        envelope = json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }})
        return HookDecision(
            outcome=Outcome.DENY, message=envelope,
            audit_fields=audit, block=True, next=Next.STOP,
        )
    return HookDecision(outcome=Outcome.WARN, message="", audit_fields=audit)


def _build_context_from_payload(payload: dict) -> HookContext:
    cwd, sid = payload.get("cwd"), payload.get("session_id")
    return HookContext(
        event_name="PreToolUse", executor_family="claude",
        executor_surface="claude", payload=payload,
        tool_name=_extract_tool_name(payload) or None,
        command_body=_extract_command(payload) or None,
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
