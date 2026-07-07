"""HC-path-claim-hard-blocks: surface over-hard activation edges.

Iterates non-terminal ``item_dependencies`` rows whose ``gate_point`` is
``activation`` and emits a WARN finding for any row whose rationale
looks path-claim-driven but lacks ``decision=directional`` evidence.
Read-only — the HC never mutates dependency rows or path claims; it
points the operator at the remediation surface
(:mod:`yoke_core.domain.path_claim_coordination_decision`) and the
``dependency-update`` command shape.

Self-skips cleanly on minimal-schema fixtures when ``item_dependencies``
or ``items`` are missing.
"""

from __future__ import annotations

from typing import List

import yoke_core.engines.doctor_report as _base
from yoke_core.domain.path_claim_hard_block_review import (
    TERMINAL_STATUSES,
    scan_non_terminal_activation_rows,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_HC_NAME = "HC-path-claim-hard-blocks"
_HC_DESC = (
    "Over-hard non-terminal activation edges authored from path-claim "
    "overlap without directional evidence"
)
_LIST_PREVIEW = 10


def hc_path_claim_hard_blocks(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    """Report activation edges that look like path-claim-only hard blocks."""
    if not _base._table_exists(conn, "item_dependencies"):
        rec.record(_HC_NAME, _HC_DESC, "PASS",
                   "item_dependencies table missing — skipping")
        return
    if not _base._table_exists(conn, "items"):
        rec.record(_HC_NAME, _HC_DESC, "PASS",
                   "items table missing — skipping")
        return

    findings = scan_non_terminal_activation_rows(conn)
    # Filter out rows whose dependent or blocking endpoint is terminal —
    # those are historical and do not need remediation.
    open_findings = [
        f for f in findings
        if f.dependent_status
        and f.dependent_status.lower() not in TERMINAL_STATUSES
    ]

    if not open_findings:
        rec.record(_HC_NAME, _HC_DESC, "PASS", "")
        return

    issues: List[str] = [
        f"- {len(open_findings)} non-terminal activation edge(s) look like "
        "path-claim-only hard blocks without directional evidence. The "
        "right shape for independent same-file edits is "
        "`--gate-point coordination_only`; for order-dependent edits, "
        "amend the rationale to include `decision=directional, ...`."
    ]
    for finding in open_findings[:_LIST_PREVIEW]:
        rationale_preview = finding.rationale.replace("\n", " ")[:120]
        issues.append(
            f"  - id={finding.dependency_id} "
            f"{finding.dependent_item} -> {finding.blocking_item} "
            f"source={finding.source} "
            f"dependent_status={finding.dependent_status}: "
            f"{finding.review.reason} "
            f"| rationale: {rationale_preview}"
        )
    if len(open_findings) > _LIST_PREVIEW:
        issues.append(
            f"  ... and {len(open_findings) - _LIST_PREVIEW} more"
        )
    issues.append(
        "- Re-classify via: `yoke claims path coordination-decision-build "
        "--item YOK-N "
        "--conflicting-claim M --paths <shared-paths>`"
    )
    issues.append(
        "- Convert to coordination_only with the listed edge refs: "
        "`yoke shepherd dependency-update <dependent> <blocking> "
        "--match-gate-point activation --gate-point coordination_only "
        "--rationale '...'`"
    )

    rec.record(_HC_NAME, _HC_DESC, "WARN", "\n".join(issues))


__all__ = ["hc_path_claim_hard_blocks"]
