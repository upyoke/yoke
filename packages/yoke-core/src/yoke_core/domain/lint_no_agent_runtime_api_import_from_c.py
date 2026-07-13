"""PreToolUse Bash hook: refuse direct Yoke imports in ``python -c`` one-liners.

Agents that reach for ``python3 -c "from yoke_core.domain.yoke_function_dispatch
import dispatch; dispatch(...)"`` are using a fallback shape for an operation
Yoke already exposes as a CLI adapter or function-call surface. The
fallback is brittle (no claim-aware gates, no telemetry, no help text) and
shows up daily in live session transcripts.

Detection: any Bash command containing ``python``/``python3`` ``-c``
followed by a quoted body that imports a Yoke-owned implementation
symbol. Post package-split surfaces include ``yoke_core.*``,
``yoke_cli.*``, and ``yoke_harness.*``; transitional legacy surfaces
include ``runtime.api.*``, ``runtime.harness.*``, and ``runtime.agents.*``.

Allowed shapes the lint stays out of:

* ``yoke <subcommand> ...`` — canonical agent shape (``items get``,
  ``claims work acquire``, ``lifecycle transition``, etc.; run
  ``yoke --help`` for the grouped catalog).
* ``python3 -m yoke_core.cli.db_router ...`` — operator-debug fallback
  inside a Yoke checkout (for function ids not yet wrapped by the ``yoke`` CLI).
* ``python3 -c "import json"`` — stdlib imports, no runtime.* reach-in.
* ``python3 -c "from collections import defaultdict"`` — same.
* ``python3 path/to/script.py`` — file invocation, not ``-c``.

Mode pinned by machine config key ``lint_agent_cli_contract_mode``
(``warn`` records audit only; ``deny`` blocks). Suppression token
``# lint:no-agent-runtime-import-check`` on the Bash command body is
recorded as audit evidence only — the rule still denies in ``deny`` mode.
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

CHECK_ID = "lint-no-agent-runtime-api-import-from-c"
HOOK_NAME = "lint-no-agent-runtime-api-import-from-c"
SUPPRESSION_TOKEN = "# lint:no-agent-runtime-import-check"

_FORBIDDEN_IMPORT_PREFIX_RE = (
    r"(?:"
    r"yoke_core(?:\.[A-Za-z_][\w]*)*|"
    r"yoke_cli(?:\.[A-Za-z_][\w]*)*|"
    r"yoke_harness(?:\.[A-Za-z_][\w]*)*|"
    r"runtime(?:\.(?:api|harness|agents)(?:\.[A-Za-z_][\w]*)*)?"
    r")"
)
_FORBIDDEN_IMPORT_RE = re.compile(
    rf"(?:^|;|\s)(?:"
    rf"from\s+{_FORBIDDEN_IMPORT_PREFIX_RE}\s+import\b|"
    rf"import\s+{_FORBIDDEN_IMPORT_PREFIX_RE}\b"
    rf")"
)
_PYTHON_TOKEN_RE = re.compile(r"^python(?:3(?:\.\d+)?)?$")


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
        "lint_no_agent_runtime_api_import_from_c", payload,
    )


def _iter_python_c_bodies(command: str):
    """Yield each ``-c`` body string from ``python(3)? -c <body>`` invocations.

    Uses ``shlex.split`` for argument-aware tokenisation so the body is
    extracted post-shell-quoting. Returns the literal quoted body so the
    caller can scan it for ``runtime.*`` imports.
    """
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return
    n = len(tokens)
    for i, tok in enumerate(tokens):
        base = os.path.basename(tok)
        if not _PYTHON_TOKEN_RE.match(base):
            continue
        for j in range(i + 1, n):
            arg = tokens[j]
            if arg == "-c" and j + 1 < n:
                yield tokens[j + 1]
                break
            if arg.startswith("-") and arg not in ("-W", "-X", "-O", "-OO", "-u", "-q", "-v"):
                if arg == "-m" or arg == "--":
                    break
                continue
            if not arg.startswith("-"):
                break


def _body_imports_runtime(body: str) -> bool:
    return bool(_FORBIDDEN_IMPORT_RE.search(body))


def _format_reason(suppression_seen: bool, mode: str) -> str:
    body = (
        "BLOCKED: `python3 -c \"from yoke_core...\"` is not the agent-facing shape "
        "for Yoke operations.\n\n"
        "The unified `yoke` CLI and HTTP function-call surface cover every "
        "operation the dispatcher exposes — reaching for `python3 -c \"...\"` "
        "bypasses claim-aware gates, telemetry, and help-text affordances.\n\n"
        "This rule targets ONLY `python3 -c \"...\"` import one-liners. "
        "`python3 -m <module>` module invocations (e.g. the `/yoke do` "
        "`python3 -m yoke_core.tools.session_init` bootstrap) are a sanctioned "
        "execution shape and are never blocked by this rule.\n\n"
        "Clean alternatives (preferred order):\n"
        "  1. Canonical agent shape — `yoke <subcommand>` covers the\n"
        "     canonical set (items get / progress-log append / structured-field\n"
        "     replace / lifecycle transition / events query / claims work\n"
        "     acquire+release / claims path register+widen / ouroboros\n"
        "     field-note append). Run `yoke --help` for the grouped\n"
        "     catalog. Examples:\n"
        "       yoke items get YOK-N status\n"
        "       yoke claims work acquire --item YOK-N --reason TEXT\n"
        "  2. Operator-debug fallback inside a Yoke checkout — for\n"
        "     function ids not yet wrapped under the `yoke` CLI:\n"
        "       python3 -m yoke_core.cli.db_router items get YOK-N status\n"
        "       python3 -m yoke_core.api.service_client claim-work --item YOK-N\n"
        "  3. HTTP function-call surface — any registered function id:\n"
        "       python3 -m yoke_core.tools.api_server start\n"
        "       curl -sS -X POST http://localhost:8765/v1/functions/call \\\n"
        "           -H 'Content-Type: application/json' \\\n"
        "           --data-binary @/tmp/envelope.json\n"
        "  4. In-tree Python — if you need a script, place it under \n"
        "     runtime/api/tools/<name>.py where imports resolve natively.\n\n"
        "Doctrine: AGENTS.md `## Code Conventions` → Operational primitives "
        "— the unified `yoke` CLI is the canonical agent interface; "
        "ad-hoc `yoke_core.*` / `runtime.*` reach-in is infrastructure / debug surface, not "
        "an agent shape."
    )
    if mode == "warn":
        body = body + "\n\n[mode=warn] this hook would block in deny mode."
    elif suppression_seen:
        body = (
            body
            + f"\n\nSuppression token `{SUPPRESSION_TOKEN}` is recorded as audit "
              "evidence (outcome=suppression_attempted) but does NOT unblock."
        )
    return append_field_note_footer(body, rule_id="lint-no-agent-runtime-api-import-from-c")


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
    hit = False
    for body in _iter_python_c_bodies(command):
        if _body_imports_runtime(body):
            hit = True
            break
    if not hit:
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
