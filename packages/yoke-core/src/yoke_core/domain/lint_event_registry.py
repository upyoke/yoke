"""Python owner for the ``lint-event-registry`` PreToolUse hook.

Replaces the inline ``python3 -c '...'`` heredocs that used to live in
``.agents/skills/yoke/scripts/lint-event-registry.sh``. The shell script
is now a thin process-entry launcher that buffers stdin, resolves the DB
path, and pipes the payload into ``python3 -m yoke_core.domain.lint_event_registry``.

Contract (preserved from the pre-Pythonization shell):

- Input: PreToolUse JSON payload on stdin.
- Output: PreToolUse deny JSON on stdout when the event is not registered,
  otherwise nothing on stdout. Deprecated events print a ``WARN`` line on
  stderr but still allow. Everything else is silent.
- Exit: always ``0`` (fail-open).
- Graceful degradation: any missing/unexpected DB, table, payload, or
  ``--name`` argument results in a silent pass-through.
- On deny, a fire-and-forget ``HarnessToolCallDenied`` event is emitted via
  the shared ``emit_denial_event`` helper with the hook-meta attribution
  fields from the payload (session_id, tool_use_id, turn_id, command
  snippet).

The module keeps the decision surface pure and side-effect-free so it can
be unit-tested directly without touching the shell wrapper. The CLI entry
point (:func:`main`) is the only code path that performs I/O.

This module is the **front door** for the lint-event-registry hook chain
and is dispatched from two harness surfaces (Claude PreToolUse via
``python3 -m yoke_core.domain.lint_event_registry``; Codex via direct
``from yoke_core.domain.lint_event_registry import evaluate``). Parsing
helpers live in :mod:`.lint_event_registry_extract`; render/emit helpers
live in :mod:`.lint_event_registry_render`. The public surface
(``evaluate``, ``decide``, ``decide_dict``, ``main``, ``HookMeta``,
``Decision``) stays here.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from typing import Optional

from yoke_core.domain import db_backend
from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.denial_field_note_footer import append_field_note_footer
from yoke_core.domain.lint_event_registry_extract import (
    HookMeta,
    extract_command,
    extract_event_name,
    extract_hook_meta,
    parse_payload,
)
from yoke_core.domain.lint_event_registry_render import (
    CHECK_ID,
    HOOK_NAME,
    TOOL_NAME,
    build_deny_json,
    build_deny_reason,
    build_deprecated_warning,
    emit_denial,
)
from runtime.harness.hook_runner.types import HookContext, HookDecision, Next, Outcome

__all__ = [
    "CHECK_ID",
    "Decision",
    "HOOK_NAME",
    "HookMeta",
    "TOOL_NAME",
    "build_deny_json",
    "build_deny_reason",
    "build_deprecated_warning",
    "decide",
    "decide_dict",
    "emit_denial",
    "evaluate",
    "extract_command",
    "extract_event_name",
    "extract_hook_meta",
    "lookup_event_status",
    "main",
    "parse_payload",
]


@dataclass
class Decision:
    """Pure decision record for a single PreToolUse invocation.

    Fields:
        action: ``"allow"``, ``"warn"``, or ``"deny"``. ``"allow"`` covers
            both "not interesting" (no emit-event.sh, no --name, missing DB,
            missing table) and "registered active". ``"warn"`` means
            "registered deprecated — allow with stderr warn". ``"deny"``
            means "unregistered — block with deny JSON and emit event".
        event_name: The extracted ``--name`` value if any, otherwise ``""``.
        stderr_message: The stderr WARN line for the deprecated path.
        deny_json: The serialized PreToolUse deny JSON for the block path.
        reason: The human-readable deny reason (also used for telemetry).
        hook_meta: Attribution metadata (always populated when available).
    """

    action: str = "allow"
    event_name: str = ""
    stderr_message: str = ""
    deny_json: str = ""
    reason: str = ""
    hook_meta: HookMeta = field(default_factory=HookMeta)


def _deny_json_with_reason(reason: str) -> str:
    """Serialize a PreToolUse deny envelope around a FOOTER-wrapped ``reason``."""
    payload = {"hookSpecificOutput": {"hookEventName": "PreToolUse",
        "permissionDecision": "deny", "permissionDecisionReason": reason}}
    return json.dumps(payload, separators=(", ", ": "))


def lookup_event_status(db_path: str, event_name: str) -> tuple[bool, Optional[str]]:
    """Look up ``event_name`` in the ``event_registry`` table.

    Returns a tuple ``(registry_available, status)``:

    - ``(False, None)`` when the DB is unavailable, the ``event_registry``
      table does not exist, or any DB error occurs. The caller must
      treat this as "graceful pass-through" (fail-open).
    - ``(True, None)`` when the registry is available but *event_name* is
      not listed. The caller must treat this as "deny".
    - ``(True, "active")`` / ``(True, "deprecated")`` / ``(True, <other>)``
      for registered events.

    This function never raises. It is the only place that reaches the
    database so that the rest of the decision surface stays pure.
    """
    try:
        conn = connect(db_path or None)
    except Exception:
        return (False, None)
    try:
        try:
            from yoke_core.domain.schema_common import _table_exists

            registry_exists = _table_exists(conn, "event_registry")
        except Exception:
            return (False, None)
        if not registry_exists:
            return (False, None)
        try:
            p = "%s" if db_backend.connection_is_postgres(conn) else "?"
            row = conn.execute(
                f"SELECT status FROM event_registry WHERE event_name={p}",
                (event_name,),
            ).fetchone()
        except Exception:
            return (False, None)
        if not row:
            return (True, None)
        status = row[0]
        if status is None:
            return (True, None)
        return (True, str(status))
    finally:
        try:
            conn.close()
        except Exception:
            pass


def decide_dict(data: Optional[dict], db_path: str) -> Decision:
    """Apply the registry rules to a parsed payload dict.

    Pure with respect to I/O besides the registry lookup delegated to
    :func:`lookup_event_status`. ``data`` of ``None`` is treated as an
    unparseable payload and yields ``allow``.
    """
    if data is None:
        return Decision(action="allow")

    hook_meta = extract_hook_meta(data)

    command = extract_command(data)
    if not command:
        return Decision(action="allow", hook_meta=hook_meta)

    if "emit-event.sh" not in command:
        return Decision(action="allow", hook_meta=hook_meta)

    event_name = extract_event_name(command)
    if not event_name:
        # help / usage invocation — allow silently.
        return Decision(action="allow", hook_meta=hook_meta)

    registry_available, status = lookup_event_status(db_path, event_name)
    if not registry_available:
        # Missing DB or missing ``event_registry`` table → graceful
        # pass-through. The shell contract requires allow-with-no-output
        # so the hook never hard-blocks a command just because the
        # registry tooling happens to be missing locally.
        return Decision(action="allow", event_name=event_name, hook_meta=hook_meta)

    if status is None:
        # Registry available but the event is not listed → deny.
        reason = append_field_note_footer(
            build_deny_reason(event_name), rule_id="lint-event-registry"
        )
        return Decision(
            action="deny",
            event_name=event_name,
            deny_json=_deny_json_with_reason(reason),
            reason=reason,
            hook_meta=hook_meta,
        )

    if status == "active":
        return Decision(action="allow", event_name=event_name, hook_meta=hook_meta)

    if status == "deprecated":
        return Decision(
            action="warn",
            event_name=event_name,
            stderr_message=build_deprecated_warning(event_name),
            hook_meta=hook_meta,
        )

    # Unknown future statuses behave like "not active" → deny.
    reason = append_field_note_footer(
        build_deny_reason(event_name), rule_id="lint-event-registry"
    )
    return Decision(
        action="deny",
        event_name=event_name,
        deny_json=_deny_json_with_reason(reason),
        reason=reason,
        hook_meta=hook_meta,
    )


def decide(raw_payload: str, db_path: str) -> Decision:
    """Evaluate a raw PreToolUse JSON payload and return a :class:`Decision`.

    Thin wrapper over :func:`decide_dict` for tests that drive the hook with
    raw JSON. Performs no I/O besides the registry lookup.
    """
    return decide_dict(parse_payload(raw_payload), db_path)


def evaluate(record: HookContext) -> HookDecision:
    """Typed entry: route a parsed PreToolUse payload through the registry rules.

    - ``allow`` → ``HookDecision(NOOP, CONTINUE)``
    - ``warn`` → emits the stderr WARN line as a side effect (preserving
      byte-equivalent stderr output from the legacy ``run``) and returns
      ``HookDecision(WARN, message="")``.
    - ``deny`` → fires the ``HarnessToolCallDenied`` event and returns
      ``HookDecision(DENY, message=<deny_json>, block=True, next=STOP)``.

    DB path is resolved from ``YOKE_DB`` first, then the canonical
    fallback. Missing/unavailable DB degrades to silent allow inside
    :func:`decide_dict`.
    """
    payload = record.payload if isinstance(record.payload, dict) else None
    db_path = os.environ.get("YOKE_DB", "") or _resolve_db_fallback()
    decision = decide_dict(payload, db_path)

    if decision.action == "warn" and decision.stderr_message:
        # Legacy byte-equivalent: WARN line on stderr, no stdout.
        print(decision.stderr_message, file=sys.stderr)
        return HookDecision(
            outcome=Outcome.WARN,
            message="",
            audit_fields={"event_name": decision.event_name},
            next=Next.CONTINUE,
        )
    if decision.action == "deny" and decision.deny_json:
        emit_denial(decision)
        return HookDecision(
            outcome=Outcome.DENY,
            message=decision.deny_json,
            audit_fields={"event_name": decision.event_name, "reason": decision.reason},
            block=True,
            next=Next.STOP,
        )
    return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)


def _resolve_db_fallback() -> str:
    """Resolve the legacy path token when ``YOKE_DB`` is unset.

    The hook's writes route through the backend factory; this fallback remains
    only for programmatic tests and older callers that still pass a db_path
    token into :func:`run(..., db_path, ...)`.

    All failures degrade to ``""``; lint hooks must remain fail-open.
    """
    try:
        from yoke_core.domain.db_helpers import resolve_db_path

        return resolve_db_path() or ""
    except Exception:
        return ""


def _build_context_from_payload(data: dict) -> HookContext:
    """Build a minimal :class:`HookContext` for the legacy stdin entry."""
    cwd, sid = data.get("cwd"), data.get("session_id")
    command = extract_command(data)
    return HookContext(
        event_name="PreToolUse",
        executor_family="claude",
        executor_surface="claude",
        payload=data,
        tool_name="Bash",
        command_body=command if isinstance(command, str) and command else None,
        cwd=cwd if isinstance(cwd, str) else None,
        session_id=sid if isinstance(sid, str) else None,
    )


def main() -> int:
    """CLI entry: stdin -> evaluate -> print deny envelope when denied.

    Honors ``YOKE_DB`` first, then the canonical Python fallback (so
    linked-worktree callers always reach the main-repo control-plane DB).
    Always exits ``0`` (fail-open).
    """
    try:
        raw = sys.stdin.read()
    except Exception:
        return 0
    data = parse_payload(raw)
    if data is None:
        return 0
    decision = evaluate(_build_context_from_payload(data))
    if decision.outcome is Outcome.DENY and decision.message:
        print(decision.message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
