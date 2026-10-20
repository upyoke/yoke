"""DB-owned project onboarding checklist runs."""

from __future__ import annotations

from typing import Any, Mapping
from yoke_contracts.timestamps import parse_instant

from yoke_contracts.onboard_checklist import (
    BRANCH_LOCAL_CHECKOUT,
    OPERATION,
    OPERATION_INIT,
    SCHEMA_NAME,
    SCHEMA_VERSION,
    ROW_IDS,
    SETUP_HANDOFF_ROW_ID,
)
from yoke_core.domain.project_onboarding_schema import (
    _ensure_columns,
    _p,
    PROJECT_ONBOARDING_RUNS_CREATE_SQL,
    PROJECT_ONBOARDING_RUN_FOREIGN_KEY_SQL,
    PROJECT_ONBOARDING_CHECKLIST_ROWS_CREATE_SQL,
)
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.project_onboarding_run_records import (
    ProjectOnboardingRunError,
    doctor_payload,
    project_payload,
    row_payload,
    summary,
)
from yoke_core.domain.project_onboarding_updates import persist_run
from yoke_core.domain.project_onboarding_facts import (
    project_rows,
    validate_observations,
    read_saved_metadata,
)
from yoke_core.domain.project_onboarding_configuration import (
    first_item_done_fact,
    project_facts,
    repaired_handoff_fact,
)

OPERATION_RUN = f"{OPERATION}.run"


def create_project_onboarding_tables(conn: Any) -> None:
    """Converge the onboarding run tables without owning the transaction."""
    conn.execute(PROJECT_ONBOARDING_RUNS_CREATE_SQL)
    conn.execute(PROJECT_ONBOARDING_CHECKLIST_ROWS_CREATE_SQL)
    _ensure_columns(conn)


def ensure_schema(conn: Any) -> None:
    """Create the onboarding run tables for a fixture database. **Tests only.**

    The schema owner is :func:`yoke_core.domain.schema_init.converge_core_schema`,
    which calls :func:`create_project_onboarding_tables` on every boot; serving
    code reaches an already-converged database and must not call this. That
    matters more here than for a bare ``CREATE TABLE IF NOT EXISTS``, because
    :func:`_ensure_columns` issues ``ALTER TABLE ... ADD COLUMN``. See
    :func:`yoke_core.domain.strategize_carry_schema.ensure_schema` for why.
    """
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
    machine_id: str | None = None,
    observations: Mapping[str, Any] | None = None,
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
        machine_id=machine_id,
        observations=observations,
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
    machine_id: str | None = None,
    observations: Mapping[str, Any] | None = None,
    operation: str = OPERATION_RUN,
    project_access: bool = False,
) -> dict[str, Any]:
    own_conn = conn is None
    selected = conn or connect()
    try:
        return persist_run(
            selected,
            run_id=run_id,
            project_id=project_id,
            branch=branch,
            checkout_path=checkout_path,
            github_repo=github_repo,
            machine_config_path=machine_config_path,
            row_status=row_status or {},
            evidence=evidence or {},
            blocker=blocker or {},
            note=note or {},
            metadata=metadata or {},
            operation=operation,
            project_access=project_access,
            machine_id=machine_id,
            observations=observations or {},
        )
    finally:
        if own_conn:
            selected.close()


def get_run(
    run_id: str,
    *,
    conn: Any | None = None,
    machine_id: str | None = None,
    observations: Mapping[str, Any] | None = None,
    project_access: bool = False,
) -> dict[str, Any]:
    own_conn = conn is None
    selected = conn or connect()
    try:
        validate_observations(observations or {}, machine_id)
        p = _p(selected)
        run = selected.execute(
            f"SELECT * FROM project_onboarding_runs WHERE run_id = {p}",
            (run_id,),
        ).fetchone()
        if run is None:
            raise ProjectOnboardingRunError(f"onboarding run not found: {run_id}")
        binding = (observations or {}).get("checkout-binding", {}).get("evidence") or {}
        if (
            binding.get("project_id") is not None
            and binding["project_id"] != run["project_id"]
        ):
            raise ProjectOnboardingRunError(
                "onboarding_checkout_mismatch: select this checkout's project or run yoke setup to rebind it."
            )
        rows = selected.execute(
            "SELECT * FROM project_onboarding_checklist_rows "
            f"WHERE run_id = {p} ORDER BY step",
            (run_id,),
        ).fetchall()
        if set(ROW_IDS) - {row["row_id"] for row in rows}:
            raise ProjectOnboardingRunError(
                "setup_checklist_incomplete: restore missing rows with yoke onboard "
                "checklist init --run-id RUN --project P, then reread current facts."
            )
        try:
            row_payloads = [row_payload(row) for row in rows]
        except (ValueError, TypeError) as exc:
            raise ProjectOnboardingRunError(
                "setup_saved_evidence_unreadable: ask the control-plane operator "
                "to restore this run's checklist evidence, then reread the checklist."
            ) from exc
        order = {row_id: index for index, row_id in enumerate(ROW_IDS)}
        row_payloads.sort(key=lambda row: order.get(row["row_id"], len(order)))
        metadata = read_saved_metadata(run["metadata_json"])
        facts = project_facts(selected, run["project_id"])
        row_payloads, readiness = project_rows(
            row_payloads,
            metadata,
            machine_id=machine_id,
            observations=observations or {},
            facts=facts,
            activation={
                **first_item_done_fact(selected, run["project_id"]),
                **repaired_handoff_fact(
                    selected,
                    run["project_id"],
                    next(
                        (row for row in rows if row["row_id"] == SETUP_HANDOFF_ROW_ID),
                        None,
                    ),
                ),
            },
            project_id=run["project_id"],
            project_access=project_access,
        )
        from yoke_core.domain.project_onboarding_next_action import select_next_action

        next_action = select_next_action(row_payloads, readiness)
        run_summary = summary(row_payloads)
        project = project_payload(run)
        local = (metadata.get("machines") or {}).get(machine_id, {})
        current_checkout = (
            (observations or {})
            .get("checkout-binding", {})
            .get("evidence", {})
            .get("checkout_path")
        )
        project["root"] = current_checkout or local.get("checkout_path")
        doctor = doctor_payload(run, run_summary, metadata)
        return {
            "schema": SCHEMA_NAME,
            "schema_version": SCHEMA_VERSION,
            "run_id": run["run_id"],
            "project_id": run["project_id"],
            "project": project,
            "machine_id": machine_id,
            "setup_readiness": readiness,
            "next_action": next_action,
            "execution_profile": metadata.get("execution_profile"),
            "profile_changed": bool(
                metadata.get("execution_profile")
                and metadata.get("profile_facts") != facts
            ),
            "branch": run["branch"],
            "checkout_path": project["root"],
            "machine_config_path": local.get("machine_config_path"),
            "github_repo": run["github_repo"],
            "status": run_summary["status"],
            "historical_status": run["status"],
            "metadata": metadata,
            "doctor": doctor,
            "secret_free": True,
            "created_at": parse_instant(run["created_at"]),
            "updated_at": parse_instant(run["updated_at"]),
            "rows": row_payloads,
            "summary": run_summary,
        }
    finally:
        if own_conn:
            selected.close()


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
