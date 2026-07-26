"""Structured execution evidence and escalation records for Dash items."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.schema_common import _table_exists

DASH_EVIDENCE_SECTION = "Execution Evidence"
DASH_ESCALATION_SECTION = "Dash Escalation"
_PASS_VALUES = frozenset({"approved", "completed", "passed", "satisfied"})
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


def _require_dash(conn: Any, item_id: int) -> dict[str, Any]:
    marker = _p(conn)
    row = _row_dict(conn.execute(
        "SELECT id, workflow_id, workflow_posture, status, project_id "
        f"FROM items WHERE id = {marker}",
        (int(item_id),),
    ))
    if row is None:
        raise LookupError(f"item {item_id} does not exist")
    if str(row["workflow_id"]) != "dash":
        raise ValueError(
            f"item {item_id} uses workflow {row['workflow_id']!r}, not Dash"
        )
    return row


def _posture(row: Mapping[str, Any]) -> dict[str, Any]:
    value = row.get("workflow_posture") or "{}"
    if isinstance(value, Mapping):
        return dict(value)
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError):
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _upsert_json_section(
    conn: Any,
    *,
    item_id: int,
    section: str,
    payload: Mapping[str, Any],
    ordering: int,
) -> None:
    marker = _p(conn)
    now = iso8601_now()
    conn.execute(
        "INSERT INTO item_sections "
        "(item_id, section_name, content, ordering, source, created_at, updated_at) "
        f"VALUES ({', '.join(marker for _ in range(7))}) "
        "ON CONFLICT(item_id, section_name) DO UPDATE SET "
        "content = excluded.content, source = excluded.source, "
        "updated_at = excluded.updated_at",
        (
            int(item_id),
            section,
            json.dumps(dict(payload), sort_keys=True, indent=2),
            ordering,
            "direct-workflow",
            now,
            now,
        ),
    )
    conn.commit()


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
    posture_checks: Optional[Mapping[str, str]] = None,
    no_changes: bool = False,
) -> dict[str, Any]:
    """Write the canonical evidence section consumed by the done gate."""
    _require_dash(conn, item_id)
    clean_result = str(result_summary).strip()
    clean_verification = str(verification_summary).strip()
    clean_status = str(verification_status).strip().casefold()
    clean_commit = str(commit_sha).strip()
    clean_merge = str(merge_sha).strip()
    files = list(dict.fromkeys(
        str(value).strip() for value in touched_files if str(value).strip()
    ))
    if not clean_result:
        raise ValueError("result_summary is required")
    if not clean_verification:
        raise ValueError("verification_summary is required")
    if clean_status not in _PASS_VALUES:
        raise ValueError("verification_status must record a passing outcome")
    for label, value in (("commit_sha", clean_commit), ("merge_sha", clean_merge)):
        if not _SHA_PATTERN.fullmatch(value):
            raise ValueError(f"{label} must be a 7-64 character git SHA")
    if not files and not no_changes:
        raise ValueError("touched_files is required unless no_changes=true")
    checks = {
        str(key): str(value).strip().casefold()
        for key, value in dict(posture_checks or {}).items()
    }
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
        "posture_checks": checks,
        "recorded_at": iso8601_now(),
    }
    _upsert_json_section(
        conn,
        item_id=item_id,
        section=DASH_EVIDENCE_SECTION,
        payload=payload,
        ordering=190,
    )
    return payload


def read_json_section(
    conn: Any,
    *,
    item_id: int,
    section: str,
) -> Optional[dict[str, Any]]:
    """Read one JSON-shaped item section."""
    if not _table_exists(conn, "item_sections"):
        return None
    marker = _p(conn)
    row = conn.execute(
        "SELECT content FROM item_sections "
        f"WHERE item_id = {marker} AND section_name = {marker}",
        (int(item_id), section),
    ).fetchone()
    if row is None:
        return None
    try:
        parsed = json.loads(str(row[0]))
    except (TypeError, ValueError):
        return None
    return dict(parsed) if isinstance(parsed, Mapping) else None


def evaluate_dash_evidence(conn: Any, item_id: int) -> DashEvidenceVerdict:
    """Validate result, verification, merge, and item-declared checks."""
    item = _require_dash(conn, item_id)
    evidence = read_json_section(
        conn, item_id=item_id, section=DASH_EVIDENCE_SECTION,
    )
    if evidence is None:
        return DashEvidenceVerdict(False, ("execution_evidence",), None)
    missing: list[str] = []
    if not str(evidence.get("result_summary") or "").strip():
        missing.append("result_summary")
    if not str(evidence.get("verification_summary") or "").strip():
        missing.append("verification_summary")
    if str(evidence.get("verification_status") or "").casefold() not in _PASS_VALUES:
        missing.append("passing_verification")
    if not _SHA_PATTERN.fullmatch(str(evidence.get("commit_sha") or "")):
        missing.append("commit_sha")
    if not _SHA_PATTERN.fullmatch(str(evidence.get("merge_sha") or "")):
        missing.append("merge_sha")
    if not evidence.get("touched_files") and not evidence.get("no_changes"):
        missing.append("touched_files")
    recorded_checks = dict(evidence.get("posture_checks") or {})
    for key, configured in _posture(item).items():
        if configured in (None, False, "", [], {}):
            continue
        if str(recorded_checks.get(key) or "").casefold() not in _PASS_VALUES:
            missing.append(f"posture_check:{key}")
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
    _require_dash(conn, item_id)
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
    _upsert_json_section(
        conn,
        item_id=item_id,
        section=DASH_ESCALATION_SECTION,
        payload=payload,
        ordering=190,
    )
    return payload


__all__ = [
    "DASH_ESCALATION_SECTION",
    "DASH_EVIDENCE_SECTION",
    "DashEvidenceVerdict",
    "evaluate_dash_evidence",
    "read_json_section",
    "record_dash_escalation",
    "record_dash_evidence",
]
