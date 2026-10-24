"""PreToolUse Bash hook: refuse ``curl`` invocations against the Yoke API.

The Yoke HTTP function-call surface (``api_server start`` on port 8765)
exists as an infrastructure debug surface — operator inspection, integration
testing, programmatic clients. It is NOT the agent shape for executing
Yoke operations. Agents that reach for ``curl http://localhost:8765/v1/...``
bypass the CLI adapter's claim-aware gates, telemetry, suppression-token
audit, and structured help text.

Detection: any Bash command that invokes ``curl`` with a URL on an API path
(``/v1``, ``/api``) at ``localhost:8765``, ``127.0.0.1:8765`` or
``0.0.0.0:8765``, or with the ``YOKE_API`` env-var substitution.

Allowed shapes the lint stays out of:

* ``curl http://127.0.0.1:8765/docs/x.html`` — a static file server on the
  same port serves no Yoke operation.
* ``curl https://api.github.com/...`` — unrelated host.
* ``curl https://npm.example.com/...`` — unrelated host.
* ``echo "curl $YOKE_API"`` — echo, not invocation.
* Any command whose substring contains ``YOKE_API`` without actually
  shelling out via ``curl``.

Mode pinned by the project-local ``.yoke/lint-config`` guard key
``lint_no_agent_curl_against_yoke_api`` (each sibling lint has its own
guard key). There is no live machine-config key
``lint_agent_cli_contract_mode``. Suppression token
``# lint:no-agent-curl-check`` is recorded as audit evidence only — the
rule still denies in ``deny`` mode.
"""

from __future__ import annotations

from yoke_core.hooks.decision_render import render_codex_decision

import json
import os
import re
import shlex
import sys
from typing import Optional, Tuple

from yoke_contracts.hook_runner.denial_identity import attach_check_id
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome
from yoke_core.domain.lint_command_extract import extract_command as _extract_command

CHECK_ID = "lint-no-agent-curl-against-yoke-api"
SUPPRESSION_TOKEN = "# lint:no-agent-curl-check"

_YOKE_API_VAR_RE = re.compile(r"\$\{?YOKE_API\}?")
_API_URL_RE = re.compile(
    r"(?:localhost|127\.0\.0\.1|0\.0\.0\.0):8765/(?:v1|api)(?:[/?#]|$)"
)


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
        "lint_no_agent_curl_against_yoke_api",
        payload,
    )


def _arg_targets_yoke_api(arg: str) -> bool:
    """Return ``True`` when ``arg`` names a Yoke API path or ``$YOKE_API``."""
    return bool(_API_URL_RE.search(arg) or _YOKE_API_VAR_RE.search(arg))


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
        "BLOCKED: `curl http://localhost:8765/v1/...` (or `/api/...`, or "
        "`curl $YOKE_API/...`) "
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
        "  2. Missing adapter — ask the control-plane operator to provide it.\n"
        "     Retain the request and selected connection; direct runtime,\n"
        "     database and HTTP calls are not an agent recovery path.\n\n"
        "Doctrine: `.yoke/docs/agents/rules/shell-and-cli.md` → Canonical yoke CLI "
        "— the unified `yoke` CLI is the canonical agent interface; "
        "HTTP-against-localhost is infrastructure / debug surface."
    )
    if mode == "warn":
        body = body + "\n\n[mode=warn] this hook would block in deny mode."
    elif suppression_seen:
        body = (
            body + f"\n\nSuppression token `{SUPPRESSION_TOKEN}` is recorded as audit "
            "evidence (outcome=suppression_attempted) but does NOT unblock."
        )
    return attach_check_id(body, check_id="lint-no-agent-curl-against-yoke-api")


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


def evaluate(record: HookContext) -> HookDecision:
    """Typed entry — pure shape parse, no subprocess fan-out."""
    payload = record.payload if isinstance(record.payload, dict) else {}
    verdict = evaluate_payload(payload)
    if verdict is None:
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    mode, reason, outcome = verdict
    audit = {
        "mode": mode,
        "reason": f"[mode={mode}] {reason}" if mode == "warn" else reason,
        "audit_outcome": outcome,
    }
    if mode == "deny":
        return HookDecision(
            outcome=Outcome.DENY,
            message=reason,
            audit_fields=audit,
            block=True,
            next=Next.STOP,
        )
    return HookDecision(outcome=Outcome.WARN, message="", audit_fields=audit)


def _build_context_from_payload(payload: dict) -> HookContext:
    cwd, sid = payload.get("cwd"), payload.get("session_id")
    return HookContext(
        event_name="PreToolUse",
        executor_family="claude",
        executor_surface="claude",
        payload=payload,
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
        print(render_codex_decision([decision], "PreToolUse")[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
