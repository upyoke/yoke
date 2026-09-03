"""Structured execution evidence and escalation records.

Shared by every direct-execution workflow that closes on its own
evidence rather than on a downstream review: Dash, which usually lands
a merge, and the floor Task shape, which never does.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.dash_close_out_progress import append_close_out_progress
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.floor_attestation import (
    evidence_workflow_mismatch,
    sha_fields_required,
    uses_agent_attested_floor,
)
from yoke_core.domain.gate_satisfier_resolution import (
    missing_done_evidence_rungs,
    record_done_evidence_rungs,
)
from yoke_core.domain.item_json_sections import (
    read_json_section,
    upsert_json_section,
)
from yoke_core.domain.workflow_definition_builders import (
    WORKFLOW_DELIVERY_MERGE_FREE,
)
from yoke_core.domain.workflow_registry import WorkflowRegistryError
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime
from yoke_contracts.dash_evidence_status import (
    is_passing as _status_is_passing,
    rejection_message as _status_rejection_message,
)

DASH_EVIDENCE_SECTION = "Execution Evidence"
DASH_ESCALATION_SECTION = "Dash Escalation"
_SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{7,64}$")


@dataclass(frozen=True)
class DashEvidenceVerdict:
    """Gate-facing result for one persisted evidence record."""

    satisfied: bool
    missing: tuple[str, ...]
    evidence: Optional[dict[str, Any]]


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _row_dict(cursor: Any) -> Optional[dict[str, Any]]:
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [str(column[0]) for column in cursor.description]
    return dict(row) if hasattr(row, "keys") else dict(zip(columns, row))


def _require_evidence_workflow(conn: Any, item_id: int) -> dict[str, Any]:
    """Return the item row, refusing a workflow that owns no such record."""
    marker = _p(conn)
    row = _row_dict(
        conn.execute(
            "SELECT id, workflow_id, workflow_posture, status, project_id "
            f"FROM items WHERE id = {marker}",
            (int(item_id),),
        )
    )
    if row is None:
        raise LookupError(f"item {item_id} does not exist")
    mismatch = evidence_workflow_mismatch(str(row["workflow_id"]), int(item_id))
    if mismatch:
        raise ValueError(mismatch)
    return row


def _delivers_merge_free(conn: Any, item_id: int) -> bool:
    """Whether the item's pinned workflow closes without a merge commit.

    An item whose workflow never produces a merge cannot supply merge
    SHAs, so its close-out uses the agent-attested floor instead. An unreadable
    pin answers no rather than guessing; the closure gate then requires SHAs.
    """
    try:
        runtime = load_item_workflow_runtime(conn, int(item_id))
    except WorkflowRegistryError:
        return False
    return runtime.policies.get("delivery") == WORKFLOW_DELIVERY_MERGE_FREE


def record_dash_evidence(
    conn: Any,
    *,
    item_id: int,
    result_summary: str,
    verification_summary: str,
    verification_status: str,
    commit_sha: str,
    merge_sha: str,
    touched_files: Sequence[str],
    tree_root: str,
    tree_head_sha: str,
    posture_checks: Optional[Mapping[str, str]] = None,
    no_changes: bool = False,
    actor_id: str = "",
    session_id: str = "",
) -> dict[str, Any]:
    """Write the canonical evidence section consumed by the done gate.

    ``tree_root`` and ``tree_head_sha`` name the tree the verification
    summary describes. The caller resolves them locally
    (:func:`yoke_core.domain.verification_tree_binding.resolve_tree_identity`)
    because only the machine holding the checkout can answer; recording
    them is what keeps a green produced against the wrong tree from
    reading exactly like a green against the right one.
    """
    _require_evidence_workflow(conn, item_id)
    clean_result = str(result_summary).strip()
    clean_verification = str(verification_summary).strip()
    clean_status = str(verification_status).strip().casefold()
    clean_commit = str(commit_sha).strip()
    clean_merge = str(merge_sha).strip()
    files = list(
        dict.fromkeys(
            str(value).strip() for value in touched_files if str(value).strip()
        )
    )
    if not clean_result:
        raise ValueError("result_summary is required")
    if not clean_verification:
        raise ValueError("verification_summary is required")
    if not _status_is_passing(clean_status):
        raise ValueError(_status_rejection_message(verification_status))
    clean_tree_root = str(tree_root).strip()
    clean_tree_head = str(tree_head_sha).strip()
    agent_attested = uses_agent_attested_floor(
        no_changes=bool(no_changes),
        merge_free_delivery=_delivers_merge_free(conn, item_id),
        merge_sha=clean_merge,
    )
    require_shas = sha_fields_required(
        no_changes=bool(no_changes),
        agent_attested=agent_attested,
    )
    sha_fields = (
        ("commit_sha", clean_commit),
        ("merge_sha", clean_merge),
        ("tree_head_sha", clean_tree_head),
    )
    # A floor close-out omits the SHAs entirely; whatever it does supply
    # still has to be a real SHA rather than a placeholder.
    for label, value in sha_fields:
        if not value and not require_shas:
            continue
        if not _SHA_PATTERN.fullmatch(value):
            raise ValueError(
                f"{label} must be a 7-64 character git SHA. Work that lands "
                "no commit closes on the agent-attested floor instead: "
                "record it with no_changes=true, or pin the item to a "
                "workflow whose delivery policy is merge-free."
            )
    if require_shas and not clean_tree_root:
        raise ValueError("tree_root is required")
    if not files and not no_changes:
        raise ValueError("touched_files is required unless no_changes=true")
    checks = {
        str(key): str(value).strip().casefold()
        for key, value in dict(posture_checks or {}).items()
    }
    record_done_evidence_rungs(
        conn,
        item_id=item_id,
        merge_recorded=bool(clean_merge),
        agent_attested=agent_attested,
    )
    recorded_at = iso8601_now()
    payload = {
        "schema": 1,
        "item_id": int(item_id),
        "result_summary": clean_result,
        "verification_summary": clean_verification,
        "verification_status": clean_status,
        "commit_sha": clean_commit,
        "merge_sha": clean_merge,
        "touched_files": files,
        "no_changes": bool(no_changes),
        "actor_id": str(actor_id or "").strip(),
        # Names the close-out that wrote this record, so a later run that
        # loses the terminal transition to it can say who finished first.
        "recorded_by_session_id": str(session_id or "").strip(),
        "posture_checks": checks,
        "verification_tree": {
            "root": clean_tree_root,
            "head_sha": clean_tree_head,
        },
        "recorded_at": recorded_at,
    }
    upsert_json_section(
        conn,
        item_id=item_id,
        section=DASH_EVIDENCE_SECTION,
        payload=payload,
        ordering=190,
    )
    append_close_out_progress(
        conn,
        item_id=item_id,
        result_summary=clean_result,
        merge_sha=clean_merge,
        recorded_at=recorded_at,
    )
    conn.commit()
    return payload


def evaluate_dash_evidence(conn: Any, item_id: int) -> DashEvidenceVerdict:
    """Validate execution evidence; posture is checked by real authorities."""
    _require_evidence_workflow(conn, item_id)
    evidence = read_json_section(
        conn,
        item_id=item_id,
        section=DASH_EVIDENCE_SECTION,
    )
    if evidence is None:
        return DashEvidenceVerdict(False, ("execution_evidence",), None)
    missing: list[str] = []
    if not str(evidence.get("result_summary") or "").strip():
        missing.append("result_summary")
    if not str(evidence.get("verification_summary") or "").strip():
        missing.append("verification_summary")
    if not _status_is_passing(evidence.get("verification_status") or ""):
        missing.append("passing_verification")
    agent_attested = uses_agent_attested_floor(
        no_changes=bool(evidence.get("no_changes")),
        merge_free_delivery=_delivers_merge_free(conn, item_id),
        merge_sha=str(evidence.get("merge_sha") or ""),
    )
    require_shas = sha_fields_required(
        no_changes=bool(evidence.get("no_changes")),
        agent_attested=agent_attested,
    )
    if require_shas:
        if not _SHA_PATTERN.fullmatch(str(evidence.get("commit_sha") or "")):
            missing.append("commit_sha")
        if not _SHA_PATTERN.fullmatch(str(evidence.get("merge_sha") or "")):
            missing.append("merge_sha")
    if not evidence.get("touched_files") and not evidence.get("no_changes"):
        missing.append("touched_files")
    missing.extend(
        missing_done_evidence_rungs(
            conn,
            item_id=item_id,
            merge_recorded=bool(str(evidence.get("merge_sha") or "")),
            agent_attested=agent_attested,
        )
    )
    return DashEvidenceVerdict(not missing, tuple(missing), evidence)


def record_dash_escalation(
    conn: Any,
    *,
    item_id: int,
    findings: str,
    issue_item_id: int,
    issue_ref: str,
) -> dict[str, Any]:
    """Link a stopped Dash to the Issue that absorbed its findings."""
    _require_evidence_workflow(conn, item_id)
    clean_findings = str(findings).strip()
    if not clean_findings:
        raise ValueError("escalation findings are required")
    payload = {
        "schema": 1,
        "dash_item_id": int(item_id),
        "issue_item_id": int(issue_item_id),
        "issue_ref": str(issue_ref).strip(),
        "findings": clean_findings,
        "recorded_at": iso8601_now(),
    }
    upsert_json_section(
        conn,
        item_id=item_id,
        section=DASH_ESCALATION_SECTION,
        payload=payload,
        ordering=190,
    )
    conn.commit()
    return payload


__all__ = [
    "DASH_ESCALATION_SECTION",
    "DASH_EVIDENCE_SECTION",
    "DashEvidenceVerdict",
    "evaluate_dash_evidence",
    "record_dash_escalation",
    "record_dash_evidence",
]
