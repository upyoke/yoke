"""HC-claim-boundary-audit: surface cross-session mutation evidence.

Read-only Doctor wrapper around
:mod:`yoke_core.domain.check_claim_boundary_audit`. Records:

- PASS when the scanner returns no findings.
- WARN when only attribution-incomplete findings exist
  (historical rows where the holder cannot be proven).
- FAIL when at least one finding carries durable evidence of a
  cross-session mutation or non-operator override.

Self-skips cleanly on minimal-schema fixtures when required tables are
absent.
"""

from __future__ import annotations

from typing import Any, List

import yoke_core.engines.doctor_report as _base
from yoke_core.domain import db_backend
from yoke_core.domain.check_claim_boundary_audit import (
    Finding,
    scan_all,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_HC_NAME = "HC-claim-boundary-audit"
_HC_DESC = (
    "Cross-session function call, claim release, and path-claim "
    "mutation evidence in the ledger"
)
_LIST_PREVIEW = 10


def _render_finding(finding: Finding) -> str:
    item_label = (
        f"YOK-{finding.item_id}"
        if finding.item_id is not None
        else "unknown"
    )
    return (
        f"  - severity={finding.severity} class={finding.finding_class} "
        f"event_id={finding.event_id} item={item_label} "
        f"holder={finding.holder_session_id or 'unknown'} "
        f"caller={finding.caller_session_id or 'unknown'} "
        f"surface={finding.mutation_surface}: {finding.rationale}"
    )


def _is_done_item_no_live_claim(conn: Any, finding: Finding) -> bool:
    if finding.item_id is None or finding.holder_session_id is not None:
        return False
    if not _base._table_exists(conn, "items"):
        return False
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"SELECT status FROM items WHERE id = {p}", (finding.item_id,),
    ).fetchone()
    return bool(row and str(row[0]).lower() == "done")


def hc_claim_boundary_audit(
    conn: Any, args: DoctorArgs, rec: RecordCollector,
) -> None:
    """Run the claim-boundary scanners and record one Doctor result."""
    if not _base._table_exists(conn, "events"):
        rec.record(_HC_NAME, _HC_DESC, "PASS",
                   "events table missing — skipping")
        return
    if not _base._table_exists(conn, "work_claims"):
        rec.record(_HC_NAME, _HC_DESC, "PASS",
                   "work_claims table missing — skipping")
        return

    findings = scan_all(conn)
    if not findings:
        rec.record(_HC_NAME, _HC_DESC, "PASS", "")
        return

    fails = [f for f in findings if f.severity == "FAIL"]
    warns = [f for f in findings if f.severity == "WARN"]
    severity = "FAIL" if fails else "WARN"

    summary_parts: List[str] = []
    if fails:
        summary_parts.append(f"{len(fails)} FAIL")
    if warns:
        summary_parts.append(f"{len(warns)} WARN")

    lines: List[str] = [
        f"- {' + '.join(summary_parts)} claim-boundary finding(s). "
        "Read-only audit — Doctor never mutates rows. Investigate via: "
        "`python3 -m yoke_core.cli.db_router events list "
        "--event-name YokeFunctionCalled`."
    ]

    historical = [f for f in warns if _is_done_item_no_live_claim(conn, f)]
    historical_ids = {f.event_id for f in historical}
    ordered = fails + [f for f in warns if f.event_id not in historical_ids] + historical
    for finding in ordered[:_LIST_PREVIEW]:
        rendered = _render_finding(finding)
        if finding.event_id in historical_ids:
            rendered += " [historical_done_item_residue]"
        lines.append(rendered)
    if len(ordered) > _LIST_PREVIEW:
        lines.append(f"  ... and {len(ordered) - _LIST_PREVIEW} more")

    rec.record(_HC_NAME, _HC_DESC, severity, "\n".join(lines))


__all__ = ["hc_claim_boundary_audit"]
