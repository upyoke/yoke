"""HC-session-cwd-binding: surface live session-cwd binding mismatches.

Diagnostic surface paired with the lint at
:mod:`yoke_core.domain.lint_session_cwd`. For each active session
that holds one or more ``work_claims``, this HC asks: is the session's
most recently observed harness cwd inside a claimed worktree, under
any project's control plane, or under a free path? If not, the
session is structurally misbound and the operator
should relaunch before a write lands.

The lint blocks individual tool calls structurally; this HC reveals
malformed sessions wholesale so the operator can spot them before any
single tool call trips the lint. Sessions with no claims pass
unconditionally — the orchestrator/control-plane session shape needs no
enforcement.

Read-only: never mutates state. Misses caused by transient telemetry
gaps degrade to "unknown" notes — false-FAILs are worse than false
allows for a diagnostic surface.
"""

from __future__ import annotations

import json
from typing import List, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.lint_session_cwd_emit import emit_health_check_failed
from yoke_core.domain.lint_session_cwd_validate import validate_targets
from yoke_core.domain.project_identity import render_item_ref

import yoke_core.engines.doctor_report as _base
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_HC_NAME = "HC-session-cwd-binding"
_HC_DESC = (
    "Active sessions with work claims must run from a claimed worktree, "
    "control plane, or free path"
)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _latest_observed_cwd(conn, session_id: str) -> Optional[str]:
    """Return the cwd from the session's most recent PreToolUse envelope."""
    p = _p(conn)
    rows = query_rows(
        conn,
        "SELECT envelope FROM events "
        f"WHERE session_id = {p} AND event_name = 'HarnessToolCallStarted' "
        "ORDER BY id DESC LIMIT 5",
        (session_id,),
    )
    for row in rows:
        envelope_raw = row["envelope"] if isinstance(row, dict) else row[0]
        if not envelope_raw:
            continue
        try:
            envelope = json.loads(envelope_raw)
        except Exception:
            continue
        cwd = envelope.get("cwd")
        if isinstance(cwd, str) and cwd.strip():
            return cwd.strip()
    return None


def hc_session_cwd_binding(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """Flag active sessions whose observed cwd is not in their claim authority."""
    if not _base._table_exists(conn, "harness_sessions"):
        rec.record(
            _HC_NAME,
            _HC_DESC,
            "PASS",
            "harness_sessions table missing — nothing to check",
        )
        return
    if not _base._table_exists(conn, "work_claims"):
        rec.record(
            _HC_NAME,
            _HC_DESC,
            "PASS",
            "work_claims table missing — nothing to check",
        )
        return

    rows = query_rows(
        conn,
        "SELECT DISTINCT session_id FROM work_claims "
        "WHERE released_at IS NULL "
        "ORDER BY session_id",
    )
    if not rows:
        rec.record(
            _HC_NAME,
            _HC_DESC,
            "PASS",
            "no active sessions with work claims",
        )
        return

    mismatches: List[str] = []
    unknown: List[str] = []
    matched_count = 0
    # The doctor runs on the machine it checks, so its own source root is
    # the root those sessions' clients report.
    from yoke_harness.hooks.client_fact_probes import yoke_source_root

    yoke_root = yoke_source_root()

    for row in rows:
        session_id = row["session_id"] if isinstance(row, dict) else row[0]
        if not session_id:
            continue
        observed_cwd = _latest_observed_cwd(conn, session_id)
        if observed_cwd is None:
            unknown.append(f"{session_id} (no recent cwd telemetry)")
            continue
        outcome = validate_targets(
            conn,
            session_id=session_id,
            targets=(),
            fallback_cwd=observed_cwd,
            yoke_root=yoke_root,
        )
        if outcome.allow:
            matched_count += 1
            continue
        claim_summary = (
            ", ".join(
                render_item_ref(conn, int(c.item_id))
                + (f"/T{c.task_num}" if c.task_num else "")
                for c in outcome.claims
            )
            or "(none)"
        )
        mismatches.append(
            f"  - session {session_id}\n"
            f"    claims:   {claim_summary}\n"
            f"    observed: {observed_cwd}\n"
            f"    offender: {outcome.offending_target}"
        )
        emit_health_check_failed(
            session_id=session_id,
            offending_target=outcome.offending_target,
            claim_count=len(outcome.claims),
        )

    note_parts: List[str] = []
    if matched_count:
        note_parts.append(f"{matched_count} matched")
    if unknown:
        note_parts.append(f"{len(unknown)} unknown")
    if mismatches:
        note_parts.append(f"{len(mismatches)} mismatched")
    note_summary = ", ".join(note_parts) or "no claim-holding sessions"

    if mismatches:
        details = f"{note_summary}\n\nMismatched sessions:\n" + "\n".join(mismatches)
        if unknown:
            details += "\n\nUnknown (no cwd telemetry):\n  - " + "\n  - ".join(unknown)
        rec.record(_HC_NAME, _HC_DESC, "FAIL", details)
        return

    if unknown:
        details = (
            note_summary
            + "\n\nUnknown (no cwd telemetry):\n  - "
            + "\n  - ".join(unknown)
        )
        rec.record(_HC_NAME, _HC_DESC, "PASS", details)
        return

    rec.record(_HC_NAME, _HC_DESC, "PASS", note_summary)


__all__ = [
    "hc_session_cwd_binding",
]
