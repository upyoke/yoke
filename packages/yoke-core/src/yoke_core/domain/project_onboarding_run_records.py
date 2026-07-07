"""Row mutation and JSON record helpers for project onboarding runs."""

from __future__ import annotations

import json
from typing import Any, Mapping

from yoke_contracts.onboard_checklist import (
    BRANCHES,
    BRANCH_MACHINE_ONLY,
    BRANCH_SOURCE_DEV_ADMIN,
    CHECKLIST_STATUSES,
    PROJECT_ROW_IDS,
    ROW_IDS,
    ROW_SPECS,
    SCHEMA_NAME,
    SETUP_HANDOFF_ROW_ID,
    SOURCE_DEV_ROW_ID,
    STATUS_BLOCKED,
    STATUS_DEFERRED,
    STATUS_NEEDED,
    STATUS_NOT_NEEDED,
    TERMINAL_STATUSES,
)

LATER_PER_ITEM_FACTS_ROW_ID = "later-per-item-facts"


class ProjectOnboardingRunError(RuntimeError):
    """A project onboarding run cannot be read or mutated."""


def upsert_default_rows(conn: Any, p: str, run_id: str, branch: str, now: str) -> None:
    existing = {
        row["row_id"]: row for row in conn.execute(
            f"SELECT * FROM project_onboarding_checklist_rows WHERE run_id = {p}",
            (run_id,),
        ).fetchall()
    }
    for spec in ROW_SPECS:
        current = existing.get(spec.row_id)
        status = current["status"] if current else default_status(spec.row_id, branch)
        evidence = current["evidence_json"] if current else "{}"
        blocker = current["blocker"] if current else ""
        note = current["note"] if current else ""
        conn.execute(
            "INSERT INTO project_onboarding_checklist_rows "
            "(run_id, row_id, step, title, layer, owner, status, hint, "
            f"evidence_json, blocker, note, updated_at) VALUES ({', '.join([p] * 12)}) "
            "ON CONFLICT (run_id, row_id) DO UPDATE SET "
            "step = EXCLUDED.step, title = EXCLUDED.title, layer = EXCLUDED.layer, "
            "owner = EXCLUDED.owner, hint = EXCLUDED.hint, updated_at = EXCLUDED.updated_at",
            (
                run_id, spec.row_id, spec.step, spec.title, spec.layer,
                spec.owner, status, spec.hint, evidence, blocker, note, now,
            ),
        )


def apply_row_updates(
    conn: Any,
    p: str,
    run_id: str,
    now: str,
    *,
    row_status: Mapping[str, str],
    evidence: Mapping[str, Any],
    blocker: Mapping[str, str | None],
    note: Mapping[str, str | None],
) -> None:
    for row_id, status in row_status.items():
        validate_row_id(row_id)
        if status not in CHECKLIST_STATUSES:
            raise ProjectOnboardingRunError(f"invalid checklist status: {status}")
        conn.execute(
            "UPDATE project_onboarding_checklist_rows "
            f"SET status = {p}, updated_at = {p} WHERE run_id = {p} AND row_id = {p}",
            (status, now, run_id, row_id),
        )
    for row_id, value in evidence.items():
        validate_row_id(row_id)
        conn.execute(
            "UPDATE project_onboarding_checklist_rows "
            f"SET evidence_json = {p}, updated_at = {p} "
            f"WHERE run_id = {p} AND row_id = {p}",
            (json_dumps(value), now, run_id, row_id),
        )
    for row_id, value in blocker.items():
        validate_row_id(row_id)
        conn.execute(
            "UPDATE project_onboarding_checklist_rows "
            f"SET blocker = {p}, updated_at = {p} WHERE run_id = {p} AND row_id = {p}",
            ("" if value is None else str(value), now, run_id, row_id),
        )
    for row_id, value in note.items():
        validate_row_id(row_id)
        conn.execute(
            "UPDATE project_onboarding_checklist_rows "
            f"SET note = {p}, updated_at = {p} WHERE run_id = {p} AND row_id = {p}",
            ("" if value is None else str(value), now, run_id, row_id),
        )


def row_payload(row: Any) -> dict[str, Any]:
    return {
        "row_id": row["row_id"],
        "step": row["step"],
        "title": row["title"],
        "phase": row["title"],
        "label": row["title"],
        "layer": row["layer"],
        "owner": row["owner"],
        "status": row["status"],
        "hint": row["hint"],
        "exit_condition": row["hint"],
        "evidence": json.loads(row["evidence_json"] or "{}"),
        "blocker": row["blocker"],
        "note": row["note"],
    }


def summary(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    by_status = {status: 0 for status in CHECKLIST_STATUSES}
    by_layer: dict[str, dict[str, int]] = {}
    blocked = [row["row_id"] for row in rows if row["status"] == STATUS_BLOCKED]
    open_rows = [
        row["row_id"] for row in rows if row["status"] not in TERMINAL_STATUSES
    ]
    for row in rows:
        status = str(row["status"])
        layer = str(row["layer"])
        by_status[status] = by_status.get(status, 0) + 1
        by_layer.setdefault(layer, {})
        by_layer[layer][status] = by_layer[layer].get(status, 0) + 1
    status = "blocked" if blocked else "complete" if not open_rows else "open"
    return {
        "status": status,
        "by_status": by_status,
        "by_layer": by_layer,
        "open_rows": open_rows,
        "blocked_rows": blocked,
        "open_row_count": len(open_rows),
        "blocked_row_count": len(blocked),
    }


def default_status(row_id: str, branch: str) -> str:
    if branch == BRANCH_MACHINE_ONLY and row_id in PROJECT_ROW_IDS:
        return STATUS_DEFERRED
    if row_id == SOURCE_DEV_ROW_ID and branch != BRANCH_SOURCE_DEV_ADMIN:
        return STATUS_NOT_NEEDED
    if row_id == LATER_PER_ITEM_FACTS_ROW_ID:
        return STATUS_DEFERRED
    if row_id == SETUP_HANDOFF_ROW_ID:
        return STATUS_NEEDED
    return STATUS_NEEDED


def validate_branch(branch: str) -> None:
    if branch not in BRANCHES:
        raise ProjectOnboardingRunError(f"invalid onboarding branch: {branch}")


def validate_row_id(row_id: str) -> None:
    if row_id not in ROW_IDS:
        raise ProjectOnboardingRunError(f"unknown checklist row: {row_id}")


def base_metadata() -> dict[str, Any]:
    return {
        "authority": "db",
        "doctor_readable": True,
        "record_shape": "project_onboarding_run.v1",
        "rendered_view_compatible": True,
    }


def run_metadata(
    payload: Mapping[str, Any],
    *,
    operation: str,
    extra: Mapping[str, Any] | None,
) -> dict[str, Any]:
    metadata = dict(payload.get("metadata") or {})
    metadata.update(base_metadata())
    metadata.update({
        "last_operation": operation,
        "doctor": payload.get("doctor") or {},
    })
    if extra:
        metadata.update(dict(extra))
    return metadata


def project_payload(run: Any) -> dict[str, Any]:
    project: dict[str, Any] = {}
    if run["project_id"] is not None:
        project["id"] = run["project_id"]
    if run["checkout_path"]:
        project["root"] = run["checkout_path"]
    if run["github_repo"]:
        project["github_repo"] = run["github_repo"]
    if run["machine_config_path"]:
        project["machine_config_path"] = run["machine_config_path"]
    return project


def doctor_payload(
    run: Any, run_summary: Mapping[str, Any], metadata: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "readable": True,
        "status": run_summary["status"],
        "schema": SCHEMA_NAME,
        "authority": metadata.get("authority", "db"),
        "run_id": run["run_id"],
        "project_id": run["project_id"],
        "open_rows": list(run_summary.get("open_rows") or []),
        "blocked_rows": list(run_summary.get("blocked_rows") or []),
    }


def with_operation(
    payload: Mapping[str, Any], *, operation: str, resumed: bool
) -> dict[str, Any]:
    record = dict(payload)
    return {
        **record,
        "operation": operation,
        "resumed": resumed,
        "run": record,
    }


def json_dumps(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ProjectOnboardingRunError(
            "onboarding checklist values must be JSON-serializable"
        ) from exc


__all__ = [
    "ProjectOnboardingRunError",
    "apply_row_updates",
    "base_metadata",
    "doctor_payload",
    "json_dumps",
    "project_payload",
    "row_payload",
    "run_metadata",
    "summary",
    "upsert_default_rows",
    "validate_branch",
    "with_operation",
]
