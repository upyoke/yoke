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

from typing import Any

import yoke_core.engines.doctor_report as _base
from yoke_core.domain.check_claim_boundary_audit_summary import audit_summary
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_HC_NAME = "HC-claim-boundary-audit"
_HC_DESC = (
    "Cross-session function call, claim release, and path-claim "
    "mutation evidence in the ledger"
)
_LIST_PREVIEW = 10


def hc_claim_boundary_audit(
    conn: Any,
    args: DoctorArgs,
    rec: RecordCollector,
) -> None:
    """Run the claim-boundary scanners and record one Doctor result."""
    if not _base._table_exists(conn, "events"):
        rec.record(_HC_NAME, _HC_DESC, "PASS", "events table missing — skipping")
        return
    if not _base._table_exists(conn, "work_claims"):
        rec.record(_HC_NAME, _HC_DESC, "PASS", "work_claims table missing — skipping")
        return

    fails, warns, sample = audit_summary(conn, preview_limit=_LIST_PREVIEW)
    if not (fails or warns):
        rec.record(
            _HC_NAME,
            _HC_DESC,
            "PASS",
            "No findings across the full audit history (configured event-id cutoff applies).",
        )
        return

    parts = []
    if fails:
        parts.append(f"{fails} FAIL")
    if warns:
        parts.append(f"{warns} WARN")
    lines = [
        f"- {' + '.join(parts)} claim-boundary finding(s) across the full audit history. "
        "Read-only audit — Doctor never mutates rows. Investigate via "
        "`yoke events query --event-name YokeFunctionCalled`."
    ]
    for finding in sample:
        item = (
            render_item_ref(conn, finding["item_id"])
            if finding["item_id"] is not None
            else "unknown"
        )
        rendered = (
            f"  - severity={finding['severity']} class={finding['finding_class']} "
            f"event_id={finding['id']} item={item} "
            f"holder={finding['holder'] or 'unknown'} caller={finding['caller'] or 'unknown'} "
            f"surface={finding['surface']}: {finding['rationale']}"
        )
        if finding["historical"]:
            rendered += " [historical_done_item_residue]"
        lines.append(rendered)
    if fails + warns > len(sample):
        lines.append(f"  ... and {fails + warns - len(sample)} more")
    rec.record(_HC_NAME, _HC_DESC, "FAIL" if fails else "WARN", "\n".join(lines))


__all__ = ["hc_claim_boundary_audit"]
