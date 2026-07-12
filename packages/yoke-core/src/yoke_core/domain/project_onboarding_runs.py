"""DB-owned project onboarding checklist runs."""

from __future__ import annotations

import json
from typing import Any, Mapping
from uuid import uuid4

from yoke_contracts.onboard_checklist import (
    BRANCH_LOCAL_CHECKOUT,
    OPERATION,
    OPERATION_INIT,
    SCHEMA_NAME,
    SCHEMA_VERSION,
    STATUS_NEEDED,
)
from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import connect, iso8601_now
from yoke_core.domain.project_onboarding_run_records import (
    ProjectOnboardingRunError,
    apply_row_updates,
    base_metadata,
    doctor_payload,
    json_dumps,
    project_payload,
    row_payload,
    run_metadata,
    summary,
    upsert_default_rows,
    validate_branch,
    with_operation,
)

OPERATION_RUN = f"{OPERATION}.run"


PROJECT_ONBOARDING_RUNS_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS project_onboarding_runs (
    run_id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    project_id INTEGER,
    branch TEXT NOT NULL,
    checkout_path TEXT,
    machine_config_path TEXT,
    github_repo TEXT,
    status TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

PROJECT_ONBOARDING_RUN_FOREIGN_KEY_SQL = (
    "FOREIGN KEY (run_id) REFERENCES project_onboarding_runs(run_id)"
)

PROJECT_ONBOARDING_CHECKLIST_ROWS_CREATE_SQL = f"""
CREATE TABLE IF NOT EXISTS project_onboarding_checklist_rows (
    run_id TEXT NOT NULL,
    row_id TEXT NOT NULL,
    step TEXT NOT NULL,
    title TEXT NOT NULL,
    layer TEXT NOT NULL,
    owner TEXT NOT NULL,
    status TEXT NOT NULL,
    hint TEXT,
    evidence_json TEXT NOT NULL,
    blocker TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (run_id, row_id),
    {PROJECT_ONBOARDING_RUN_FOREIGN_KEY_SQL}
)
"""


def create_project_onboarding_tables(conn: Any) -> None:
    """Converge the onboarding run tables without owning the transaction."""
    conn.execute(PROJECT_ONBOARDING_RUNS_CREATE_SQL)
    conn.execute(PROJECT_ONBOARDING_CHECKLIST_ROWS_CREATE_SQL)
    _ensure_columns(conn)


def ensure_schema(conn: Any) -> None:
    create_project_onboarding_tables(conn)
    conn.commit()


def init_run(
    *,
    conn: Any | None = None,
    run_id: str | None = None,
    project_id: int | None = None,
    branch: str = BRANCH_LOCAL_CHECKOUT,
    checkout_path: str | None = None,
    machine_config_path: str | None = None,
    github_repo: str | None = None,
    row_status: Mapping[str, str] | None = None,
    evidence: Mapping[str, Any] | None = None,
    blocker: Mapping[str, str | None] | None = None,
    note: Mapping[str, str | None] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return update_run(
        conn=conn,
        run_id=run_id,
        project_id=project_id,
        branch=branch,
        checkout_path=checkout_path,
        machine_config_path=machine_config_path,
        github_repo=github_repo,
        row_status=row_status,
        evidence=evidence,
        blocker=blocker,
        note=note,
        metadata=metadata,
        operation=OPERATION_INIT,
    )


def update_run(
    *,
    conn: Any | None = None,
    run_id: str | None = None,
    project_id: int | None = None,
    branch: str | None = None,
    checkout_path: str | None = None,
    machine_config_path: str | None = None,
    github_repo: str | None = None,
    row_status: Mapping[str, str] | None = None,
    evidence: Mapping[str, Any] | None = None,
    blocker: Mapping[str, str | None] | None = None,
    note: Mapping[str, str | None] | None = None,
    metadata: Mapping[str, Any] | None = None,
    operation: str = OPERATION_RUN,
) -> dict[str, Any]:
    own_conn = conn is None
    selected = conn or connect()
    try:
        ensure_schema(selected)
        selected_id = _normalize_run_id(run_id or f"run-{uuid4().hex[:12]}")
        resumed = _run_exists(selected, selected_id)
        existing = _fetch_run(selected, selected_id)
        selected_branch = branch or (
            existing["branch"] if existing is not None else BRANCH_LOCAL_CHECKOUT
        )
        validate_branch(selected_branch)
        now = iso8601_now()
        p = _p(selected)
        _upsert_run(
            selected,
            selected_id,
            project_id,
            selected_branch,
            checkout_path,
            machine_config_path,
            github_repo,
            now,
        )
        upsert_default_rows(selected, p, selected_id, selected_branch, now)
        apply_row_updates(
            selected,
            p,
            selected_id,
            now,
            row_status=row_status or {},
            evidence=evidence or {},
            blocker=blocker or {},
            note=note or {},
        )
        payload = get_run(selected_id, conn=selected)
        _set_run_status_and_metadata(
            selected,
            selected_id,
            payload["summary"]["status"],
            run_metadata(payload, operation=operation, extra=metadata),
            now,
        )
        selected.commit()
        payload = get_run(selected_id, conn=selected)
        return with_operation(payload, operation=operation, resumed=resumed)
    finally:
        if own_conn:
            selected.close()


def get_run(run_id: str, *, conn: Any | None = None) -> dict[str, Any]:
    own_conn = conn is None
    selected = conn or connect()
    try:
        ensure_schema(selected)
        p = _p(selected)
        run = selected.execute(
            f"SELECT * FROM project_onboarding_runs WHERE run_id = {p}",
            (run_id,),
        ).fetchone()
        if run is None:
            raise ProjectOnboardingRunError(f"onboarding run not found: {run_id}")
        rows = selected.execute(
            "SELECT * FROM project_onboarding_checklist_rows "
            f"WHERE run_id = {p} ORDER BY step",
            (run_id,),
        ).fetchall()
        row_payloads = [row_payload(row) for row in rows]
        run_summary = summary(row_payloads)
        metadata = json.loads(run["metadata_json"] or "{}")
        project = project_payload(run)
        doctor = doctor_payload(run, run_summary, metadata)
        return {
            "schema": SCHEMA_NAME,
            "schema_version": int(run["schema_version"]),
            "run_id": run["run_id"],
            "project_id": run["project_id"],
            "project": project,
            "branch": run["branch"],
            "checkout_path": run["checkout_path"],
            "machine_config_path": run["machine_config_path"],
            "github_repo": run["github_repo"],
            "status": run["status"],
            "metadata": metadata,
            "doctor": doctor,
            "secret_free": True,
            "created_at": run["created_at"],
            "updated_at": run["updated_at"],
            "rows": row_payloads,
            "summary": run_summary,
        }
    finally:
        if own_conn:
            selected.close()


def _upsert_run(
    conn: Any,
    run_id: str,
    project_id: int | None,
    branch: str,
    checkout_path: str | None,
    machine_config_path: str | None,
    github_repo: str | None,
    now: str,
) -> None:
    p = _p(conn)
    metadata = json_dumps(base_metadata())
    conn.execute(
        "INSERT INTO project_onboarding_runs "
        "(run_id, schema_version, project_id, branch, checkout_path, "
        "machine_config_path, github_repo, status, metadata_json, created_at, updated_at) "
        f"VALUES ({', '.join([p] * 11)}) "
        "ON CONFLICT (run_id) DO UPDATE SET "
        "project_id = COALESCE(EXCLUDED.project_id, project_onboarding_runs.project_id), "
        "branch = EXCLUDED.branch, "
        "checkout_path = COALESCE(EXCLUDED.checkout_path, project_onboarding_runs.checkout_path), "
        "machine_config_path = COALESCE(EXCLUDED.machine_config_path, project_onboarding_runs.machine_config_path), "
        "github_repo = COALESCE(EXCLUDED.github_repo, project_onboarding_runs.github_repo), "
        "updated_at = EXCLUDED.updated_at",
        (
            run_id, SCHEMA_VERSION, project_id, branch, checkout_path,
            machine_config_path, github_repo, STATUS_NEEDED, metadata, now, now,
        ),
    )


def _set_run_status_and_metadata(
    conn: Any, run_id: str, status: str, metadata: Mapping[str, Any], now: str
) -> None:
    p = _p(conn)
    conn.execute(
        "UPDATE project_onboarding_runs "
        f"SET status = {p}, metadata_json = {p}, updated_at = {p} WHERE run_id = {p}",
        (status, json_dumps(metadata), now, run_id),
    )


def _run_exists(conn: Any, run_id: str) -> bool:
    return _fetch_run(conn, run_id) is not None


def _fetch_run(conn: Any, run_id: str) -> Any | None:
    p = _p(conn)
    return conn.execute(
        f"SELECT * FROM project_onboarding_runs WHERE run_id = {p}",
        (run_id,),
    ).fetchone()


def _normalize_run_id(run_id: str) -> str:
    selected = run_id.strip()
    if not selected:
        raise ProjectOnboardingRunError("run_id is required")
    return selected


def _ensure_columns(conn: Any) -> None:
    row_columns = {
        "evidence_json": "TEXT NOT NULL DEFAULT '{}'",
        "blocker": "TEXT NOT NULL DEFAULT ''",
        "note": "TEXT NOT NULL DEFAULT ''",
    }
    for column, definition in row_columns.items():
        _ensure_column(conn, "project_onboarding_checklist_rows", column, definition)


def _ensure_column(conn: Any, table: str, column: str, definition: str) -> None:
    if _column_exists(conn, table, column):
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _column_exists(conn: Any, table: str, column: str) -> bool:
    if db_backend.connection_is_postgres(conn):
        p = _p(conn)
        return conn.execute(
            "SELECT 1 FROM information_schema.columns "
            f"WHERE table_name = {p} AND column_name = {p}",
            (table, column),
        ).fetchone() is not None
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(_column_name(row) == column for row in rows)


def _column_name(row: Any) -> str:
    return row["name"] if hasattr(row, "keys") else row[1]


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


__all__ = [
    "PROJECT_ONBOARDING_CHECKLIST_ROWS_CREATE_SQL",
    "PROJECT_ONBOARDING_RUN_FOREIGN_KEY_SQL",
    "PROJECT_ONBOARDING_RUNS_CREATE_SQL",
    "ProjectOnboardingRunError",
    "create_project_onboarding_tables",
    "ensure_schema",
    "get_run",
    "init_run",
    "update_run",
    "OPERATION_RUN",
]
