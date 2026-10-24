"""Python owner for the ``lint-event-registry`` PreToolUse hook.

Replaces the inline ``python3 -c '...'`` heredocs that used to live in
``.agents/skills/yoke/scripts/lint-event-registry.sh``. The shell script
is now a thin process-entry launcher that buffers stdin, resolves the DB
path, and pipes the payload into ``python3 -m yoke_core.domain.lint_event_registry``.

Contract (preserved from the pre-Pythonization shell):

- Input: PreToolUse JSON payload on stdin.
- Output: PreToolUse deny JSON on stdout when the event is not registered,
  otherwise nothing on stdout. Everything else is silent.
- Exit: always ``0`` (fail-open).
- Graceful degradation: any missing/unexpected DB, table, payload, or
  ``--name`` argument results in a silent pass-through.
- On deny, :func:`evaluate` returns a blocking decision whose
  ``audit_fields`` carry the deny reason; the shared hook runner records
  the denial row from it.

The module keeps the decision surface pure and side-effect-free so it can
be unit-tested directly without touching the shell wrapper. The CLI entry
point (:func:`main`) is the only code path that performs I/O.

This module is the **front door** for the lint-event-registry hook chain
and is dispatched from two harness surfaces (Claude PreToolUse via
``python3 -m yoke_core.domain.lint_event_registry``; Codex via direct
``from yoke_core.domain.lint_event_registry import evaluate``). Parsing
helpers live in :mod:`.lint_event_registry_extract`; deny-payload render
helpers live in :mod:`.lint_event_registry_render`. The public surface
(``evaluate``, ``decide``, ``decide_dict``, ``main``,
``Decision``) stays here.
"""

from __future__ import annotations

from yoke_core.hooks.decision_render import render_codex_decision
import os
import sys
from dataclasses import dataclass
from typing import Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import connect
from yoke_contracts.hook_runner.denial_identity import attach_check_id
from yoke_core.domain.lint_command_extract import extract_command
from yoke_core.domain.lint_event_registry_extract import (
    extract_event_name,
    parse_payload,
)
from yoke_core.domain.lint_event_registry_render import (
    CHECK_ID,
    build_deny_reason,
)
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome

__all__ = [
    "CHECK_ID",
    "Decision",
    "build_deny_reason",
    "decide",
    "decide_dict",
    "evaluate",
    "extract_command",
    "extract_event_name",
    "lookup_event_registered",
    "main",
    "parse_payload",
]


@dataclass
class Decision:
    """Pure decision record for a single PreToolUse invocation.

    Fields:
        action: ``"allow"`` or ``"deny"``. ``"allow"`` covers both "not
            interesting" (no emit-event.sh, no --name, missing DB, missing
            table) and "registered". ``"deny"`` means "unregistered — block
            with a plain reason".
        event_name: The extracted ``--name`` value if any, otherwise ``""``.
        reason: The human-readable deny reason (also the audit reason).
    """

    action: str = "allow"
    event_name: str = ""
    reason: str = ""


def lookup_event_registered(db_path: str, event_name: str) -> tuple[bool, bool]:
    """Return ``(registry_available, registered)`` for ``event_name``.

    ``registry_available`` is ``False`` when the DB is unavailable, the
    ``event_registry`` table does not exist, or any DB error occurs; the
    caller treats that as a graceful pass-through (fail-open). This
    function never raises. It is the only place that reaches the database
    so that the rest of the decision surface stays pure.
    """
    try:
        conn = connect(db_path or None)
    except Exception:
        return (False, False)
    try:
        try:
            from yoke_core.domain.schema_common import _table_exists

            if not _table_exists(conn, "event_registry"):
                return (False, False)
            p = "%s" if db_backend.connection_is_postgres(conn) else "?"
            row = conn.execute(
                f"SELECT 1 FROM event_registry WHERE event_name={p}",
                (event_name,),
            ).fetchone()
        except Exception:
            return (False, False)
        return (True, row is not None)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def decide_dict(data: Optional[dict], db_path: str) -> Decision:
    """Apply the registry rules to a parsed payload dict.

    Pure with respect to I/O besides the registry lookup delegated to
    :func:`lookup_event_registered`. ``data`` of ``None`` is treated as an
    unparseable payload and yields ``allow``.
    """
    if data is None:
        return Decision(action="allow")

    command = extract_command(data)
    if not command:
        return Decision(action="allow")

    if "emit-event.sh" not in command:
        return Decision(action="allow")

    event_name = extract_event_name(command)
    if not event_name:
        # help / usage invocation — allow silently.
        return Decision(action="allow")

    registry_available, registered = lookup_event_registered(db_path, event_name)
    if not registry_available or registered:
        # Missing DB or missing ``event_registry`` table → graceful
        # pass-through, so the hook never hard-blocks a command just because
        # the registry tooling happens to be missing locally.
        return Decision(action="allow", event_name=event_name)

    reason = attach_check_id(
        build_deny_reason(event_name), check_id="lint-event-registry"
    )
    return Decision(
        action="deny",
        event_name=event_name,
        reason=reason,
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
    - ``deny`` → ``HookDecision(DENY, message=<reason>, block=True,
      next=STOP)`` whose ``audit_fields`` carry the deny reason.

    DB path is resolved from ``YOKE_DB`` first, then the canonical
    fallback. Missing/unavailable DB degrades to silent allow inside
    :func:`decide_dict`.
    """
    payload = record.payload if isinstance(record.payload, dict) else None
    db_path = os.environ.get("YOKE_DB", "") or _resolve_db_fallback()
    decision = decide_dict(payload, db_path)

    if decision.action == "deny" and decision.reason:
        return HookDecision(
            outcome=Outcome.DENY,
            message=decision.reason,
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
        print(render_codex_decision([decision], "PreToolUse")[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
