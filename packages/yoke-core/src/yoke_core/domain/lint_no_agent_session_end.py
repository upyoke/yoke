"""PreToolUse Bash hook: refuse agent-context ``service_client session-end``.

The harness owns session lifetime — ``Stop`` and ``SessionEnd`` hooks route
through ``yoke_core.hooks.session_end_cleanup`` and call
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

The guard always returns a deny; the hook runner's mode gate applies the
``.yoke/lint-config`` guard key ``lint_no_agent_session_end`` (``warn``
downgrades it to an audit-only row). Suppression token
``# lint:no-agent-session-end-check`` is recorded as audit evidence only —
it does not unblock.
"""

from __future__ import annotations

from yoke_core.hooks.decision_render import render_codex_decision

import json
import os
import shlex
import sys
from typing import Optional, Tuple

from yoke_contracts.hook_runner.denial_identity import attach_check_id
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome
from yoke_core.domain.lint_command_extract import extract_command as _extract_command

CHECK_ID = "lint-no-agent-session-end"
SUPPRESSION_TOKEN = "# lint:no-agent-session-end-check"

_BANNED_SUBCOMMANDS = ("session-end", "session-end-if-empty")


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


def _format_reason(suppression_seen: bool) -> str:
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
        "Doctrine: `.yoke/docs/agents/rules/claude-sessions.md` → Session "
        "end and recovery. Skill prose, agent bodies, and dispatch context "
        "teach the release primitive; the harness owns the session."
    )
    if suppression_seen:
        body = (
            body + f"\n\nSuppression token `{SUPPRESSION_TOKEN}` is recorded "
            "as audit evidence (outcome=suppression_attempted) but does "
            "NOT unblock."
        )
    return attach_check_id(body, check_id=CHECK_ID)


def evaluate_payload(payload: dict) -> Optional[Tuple[str, str]]:
    """Apply the rule; return ``(reason, audit_outcome)`` on a hit, else None."""
    if not isinstance(payload, dict):
        return None
    command = _extract_command(payload)
    if not command:
        return None
    if not _command_invokes_banned_session_end(command):
        return None
    suppression_seen = SUPPRESSION_TOKEN in command
    reason = _format_reason(suppression_seen)
    return reason, "suppression_attempted" if suppression_seen else "denied"


def evaluate(record: HookContext) -> HookDecision:
    """Typed entry — pure shape parse, no subprocess fan-out."""
    if record.tool_name and record.tool_name != "Bash":
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    payload = record.payload if isinstance(record.payload, dict) else {}
    verdict = evaluate_payload(payload)
    if verdict is None:
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    reason, outcome = verdict
    return HookDecision(
        outcome=Outcome.DENY,
        message=reason,
        audit_fields={"reason": reason, "audit_outcome": outcome},
        block=True,
        next=Next.STOP,
    )


def _build_context_from_payload(payload: dict) -> HookContext:
    cwd, sid = payload.get("cwd"), payload.get("session_id")
    tool_name = payload.get("tool_name")
    return HookContext(
        event_name="PreToolUse",
        executor_family="claude",
        executor_surface="claude",
        payload=payload,
        tool_name=tool_name if isinstance(tool_name, str) and tool_name else None,
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
        print(render_codex_decision([decision], "PreToolUse")[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
