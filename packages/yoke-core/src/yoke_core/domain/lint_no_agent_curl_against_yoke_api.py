"""PreToolUse Bash hook: refuse ``curl`` invocations against the Yoke API.

The Yoke HTTP function-call surface (``api_server start`` on port 8765)
exists as an infrastructure debug surface — operator inspection, integration
testing, programmatic clients. It is NOT the agent shape for executing
Yoke operations. Agents that reach for ``curl http://localhost:8765/v1/...``
bypass the CLI adapter's claim-aware gates, telemetry, suppression-token
audit, and structured help text.

Detection: any Bash command that invokes ``curl`` with a URL pointing at the
Yoke API host — ``localhost:8765``, ``127.0.0.1:8765``, ``0.0.0.0:8765``,
or the ``YOKE_API`` env-var substitution.

Allowed shapes the lint stays out of:

* ``curl https://api.github.com/...`` — unrelated host.
* ``curl https://npm.example.com/...`` — unrelated host.
* ``echo "curl $YOKE_API"`` — echo, not invocation.
* Any command whose substring contains ``YOKE_API`` without actually
  shelling out via ``curl``.

Mode pinned by machine config key ``lint_agent_cli_contract_mode`` (shared
with the sibling import-from-c lint). Suppression token
``# lint:no-agent-curl-check`` is recorded as audit evidence only — the
rule still denies in ``deny`` mode.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from typing import Optional, Tuple

from yoke_core.domain.denial_field_note_footer import append_field_note_footer
from runtime.harness.hook_runner.types import HookContext, HookDecision, Next, Outcome

CHECK_ID = "lint-no-agent-curl-against-yoke-api"
HOOK_NAME = "lint-no-agent-curl-against-yoke-api"
SUPPRESSION_TOKEN = "# lint:no-agent-curl-check"

_YOKE_HOSTS = (
    "localhost:8765",
    "127.0.0.1:8765",
    "0.0.0.0:8765",
)
_YOKE_API_VAR_RE = re.compile(r"\$\{?YOKE_API\}?")
_HOST_RE = re.compile(
    r"https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0):8765\b"
)


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
    # Single surface: resolve via the lint_config registry (.yoke/lint-config).
    from yoke_core.domain import lint_config

    return lint_config.resolve_mode_for_payload(
        "lint_no_agent_curl_against_yoke_api", payload,
    )


def _arg_targets_yoke_api(arg: str) -> bool:
    """Return ``True`` when ``arg`` is a URL/host pointing at Yoke's API."""
    if _HOST_RE.search(arg):
        return True
    if _YOKE_API_VAR_RE.search(arg):
        return True
    if any(host in arg for host in _YOKE_HOSTS):
        return True
    return False


def _command_targets_yoke_api(command: str) -> bool:
    """Return ``True`` when the command shells out to ``curl`` with a Yoke URL.

    Uses ``shlex.split`` so the curl token is recognised after shell
    quoting; iterates each ``curl`` invocation in the (potentially
    compound) command and inspects its non-flag args for Yoke-API URLs.
    """
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return False
    n = len(tokens)
    for i, tok in enumerate(tokens):
        base = os.path.basename(tok)
        if base != "curl":
            continue
        for j in range(i + 1, n):
            arg = tokens[j]
            if arg in (";", "&&", "||", "|", "&"):
                break
            if _arg_targets_yoke_api(arg):
                return True
    return False


def _format_reason(suppression_seen: bool, mode: str) -> str:
    body = (
        "BLOCKED: `curl http://localhost:8765/...` (or `curl $YOKE_API/...`) "
        "is not the agent-facing shape for Yoke operations.\n\n"
        "The Yoke HTTP function-call surface is an infrastructure / debug "
        "surface — operator inspection, integration testing, programmatic "
        "clients. Agents drive Yoke operations through the unified `yoke` "
        "CLI, which carries claim-aware gates, telemetry, and structured help "
        "text.\n\n"
        "Clean alternatives (preferred order):\n"
        "  1. Canonical agent shape — `yoke <subcommand>` (the canonical\n"
        "     CLI set covers\n"
        "     items.get / items.progress-log append / items.structured-field\n"
        "     replace / lifecycle.transition / events.query /\n"
        "     claims.work.{acquire,release} / claims.path.{register,widen} /\n"
        "     ouroboros.field-note append). Run `yoke --help` for the\n"
        "     grouped catalog.\n"
        "  2. Operator-debug fallback inside a Yoke checkout — for function\n"
        "     ids not yet wrapped under the `yoke` CLI:\n"
        "       python3 -m yoke_core.api.service_client <subcommand> ...\n"
        "       python3 -m yoke_core.cli.db_router <subcommand> ...\n"
        "  3. Function-call dispatch via Python — when you genuinely need\n"
        "     a generic envelope from a script under runtime/api/tools/:\n"
        "       from yoke_core.domain.yoke_function_dispatch import dispatch\n"
        "  4. HTTP curl — operator/debug only, never the agent shape.\n\n"
        "Doctrine: AGENTS.md `## Code Conventions` → Operational primitives "
        "— the unified `yoke` CLI is the canonical agent interface; "
        "HTTP-against-localhost is infrastructure / debug surface."
    )
    if mode == "warn":
        body = body + "\n\n[mode=warn] this hook would block in deny mode."
    elif suppression_seen:
        body = (
            body
            + f"\n\nSuppression token `{SUPPRESSION_TOKEN}` is recorded as audit "
              "evidence (outcome=suppression_attempted) but does NOT unblock."
        )
    return append_field_note_footer(body, rule_id="lint-no-agent-curl-against-yoke-api")


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
    if not _command_targets_yoke_api(command):
        return None
    suppression_seen = SUPPRESSION_TOKEN in command
    mode = _read_mode(payload)
    reason = _format_reason(suppression_seen, mode)
    outcome = "suppression_attempted" if suppression_seen else "denied"
    return (mode, reason, outcome)


def _emit_audit_event(payload: dict, reason: str, mode: str, outcome: str) -> None:
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
    cwd, sid = payload.get("cwd"), payload.get("session_id")
    return HookContext(event_name="PreToolUse", executor_family="claude",
        executor_surface="claude", payload=payload,
        tool_name=_extract_tool_name(payload) or None,
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


if __name__ == "__main__":
    sys.exit(main())
