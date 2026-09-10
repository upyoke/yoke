"""Compact screenshot facts for human decisions about items and runs."""

from __future__ import annotations

import json
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.qa_merging_identity import recorded_head_sha
from yoke_core.domain.schema_common import _table_exists


def _value(row: Any, key: str, index: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[index]


def _metadata(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(str(raw or "{}"))
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _is_screenshot(artifact_type: Any, content_type: Any) -> bool:
    return "screenshot" in str(artifact_type or "").lower() or str(
        content_type or ""
    ).lower().startswith("image/")


def _revision(raw: Any) -> str:
    serialized = json.dumps(raw) if isinstance(raw, dict) else raw
    return recorded_head_sha(serialized)


def related_screenshot_evidence(
    conn: Any,
    *,
    item_id: Optional[int] = None,
    deployment_run_id: Optional[str] = None,
    expected_revision: Optional[str] = None,
) -> dict[str, Any]:
    """Return latest-result screenshots tied to exactly one item or deploy run.

    Standalone plan evidence is deliberately excluded: an approval must not
    imply that an unattached plan proved its item or release. The returned
    state distinguishes no attachment, an attached run with no screenshots,
    failed evidence, and evidence for an older revision. A review result may
    point back to its immutable capture run; those screenshots remain visible.
    """
    required = ("qa_requirements", "qa_runs", "qa_artifacts")
    if not all(_table_exists(conn, table) for table in required):
        return {"state": "unavailable", "screenshots": [], "requirement_count": 0}
    if (item_id is None) == (deployment_run_id is None):
        raise ValueError("name exactly one evidence subject")
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    if item_id is not None:
        subject = f"(q.item_id={marker} OR q.epic_id={marker})"
        params: tuple[Any, ...] = (int(item_id), int(item_id))
    else:
        subject = f"q.deployment_run_id={marker}"
        params = (str(deployment_run_id),)
    latest_rows = conn.execute(
        "SELECT q.id AS requirement_id, r.id AS run_id, r.verdict, "
        "r.execution_status, r.raw_result FROM qa_requirements q "
        "LEFT JOIN qa_runs r ON r.id=(SELECT latest.id FROM qa_runs latest "
        "WHERE latest.qa_requirement_id=q.id "
        "ORDER BY latest.created_at DESC, latest.id DESC LIMIT 1) "
        f"WHERE {subject} ORDER BY q.id",
        params,
    ).fetchall()
    requirement_ids = {int(_value(row, "requirement_id", 0)) for row in latest_rows}
    latest: dict[int, dict[str, Any]] = {}
    source_run_ids: set[int] = set()
    for row in latest_rows:
        requirement_id = int(_value(row, "requirement_id", 0))
        if requirement_id in latest:
            continue
        run_id = _value(row, "run_id", 1)
        raw_result = _value(row, "raw_result", 4)
        payload = _metadata(raw_result)
        capture_run_id = payload.get("capture_run_id")
        source_runs = {int(run_id)} if run_id is not None else set()
        if str(capture_run_id or "").isdigit():
            source_runs.add(int(capture_run_id))
        source_run_ids.update(source_runs)
        latest[requirement_id] = {
            "source_runs": source_runs,
            "revision": _revision(raw_result),
        }
    evidence_rows = []
    if source_run_ids:
        markers = ", ".join(marker for _ in source_run_ids)
        evidence_rows = conn.execute(
            "SELECT r.qa_requirement_id AS requirement_id, r.id AS run_id, "
            "r.verdict, r.execution_status, r.raw_result, a.id AS artifact_id, "
            "a.artifact_type, a.content_type, a.artifact_handle, a.metadata "
            "FROM qa_runs r JOIN qa_artifacts a ON a.qa_run_id=r.id "
            f"WHERE r.id IN ({markers}) ORDER BY r.qa_requirement_id, a.id",
            tuple(sorted(source_run_ids)),
        ).fetchall()
    screenshots = []
    failed = False
    revisions: set[str] = set()
    for row in evidence_rows:
        requirement_id = int(_value(row, "requirement_id", 0))
        run_id = _value(row, "run_id", 1)
        if run_id is None or int(run_id) not in latest[requirement_id]["source_runs"]:
            continue
        revision = _revision(_value(row, "raw_result", 4))
        revision = revision or latest[requirement_id]["revision"]
        if revision:
            revisions.add(revision)
        verdict = str(_value(row, "verdict", 2) or "").lower()
        execution = str(_value(row, "execution_status", 3) or "").lower()
        failed = failed or verdict in {"fail", "error"} or execution == "capture_failed"
        artifact_id = _value(row, "artifact_id", 5)
        artifact_type = _value(row, "artifact_type", 6)
        content_type = _value(row, "content_type", 7)
        if artifact_id is None or not _is_screenshot(artifact_type, content_type):
            continue
        screenshots.append(
            {
                "artifact_id": int(artifact_id),
                "artifact_type": str(artifact_type),
                "content_type": content_type,
                "artifact_handle": _value(row, "artifact_handle", 8),
                "metadata": _metadata(_value(row, "metadata", 9)),
                "requirement_id": requirement_id,
                "run_id": int(run_id),
                "code_revision": revision,
            }
        )
    state = "absent" if not requirement_ids else "missing"
    if screenshots:
        state = "failed" if failed else "attached"
        expected = str(expected_revision or "").strip()
        if expected and revisions and expected not in revisions:
            state = "stale"
        elif expected and not revisions:
            state = "revision_unknown"
    return {
        "state": state,
        "screenshots": screenshots,
        "screenshot_count": len(screenshots),
        "requirement_count": len(requirement_ids),
        "revisions": sorted(revisions),
        "expected_revision": expected_revision,
    }


__all__ = ["related_screenshot_evidence"]
