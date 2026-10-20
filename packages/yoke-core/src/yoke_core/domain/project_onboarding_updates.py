"""Atomic persistence of shared choices and machine-scoped onboarding rows."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from yoke_contracts.onboard_checklist import (
    BRANCH_LOCAL_CHECKOUT,
    MACHINE_ROW_IDS,
    SCHEMA_VERSION,
    STATUS_NEEDED,
)
from yoke_core.domain.db_helpers import instant_parameter, utc_now
from yoke_core.domain.project_onboarding_schema import _p
from yoke_core.domain.project_onboarding_scope import resolve_run
from yoke_core.domain.project_onboarding_run_records import (
    ProjectOnboardingRunError,
    apply_row_updates,
    base_metadata,
    json_dumps,
    run_metadata,
    upsert_default_rows,
    validate_branch,
    with_operation,
)
from yoke_core.domain.project_onboarding_configuration import (
    profile_snapshot,
    project_facts,
)
from yoke_core.domain.project_onboarding_facts import (
    update_machine_choices,
    validate_updates,
    validate_observations,
    read_saved_metadata,
)


def persist_run(
    conn: Any,
    *,
    run_id: str | None,
    project_id: int | None,
    branch: str | None,
    checkout_path: str | None,
    github_repo: str | None,
    machine_config_path: str | None,
    row_status: Mapping[str, str],
    evidence: Mapping[str, Any],
    blocker: Mapping[str, Any],
    note: Mapping[str, Any],
    metadata: Mapping[str, Any],
    operation: str,
    machine_id: str | None,
    observations: Mapping[str, Any],
    project_access: bool = False,
) -> dict[str, Any]:
    from yoke_core.domain.project_onboarding_runs import get_run

    validate_updates(
        row_status=row_status,
        evidence=evidence,
        blocker=blocker,
        note=note,
        metadata=metadata,
        machine_id=machine_id,
    )
    validate_observations(observations, machine_id)
    conn.execute("SAVEPOINT onboarding_update")
    try:
        selected_id, existing = resolve_run(
            conn, run_id=run_id, project_id=project_id, lock=True
        )
        selected_project = project_id if existing is None else existing["project_id"]
        binding = observations.get("checkout-binding", {}).get("evidence") or {}
        if (
            binding.get("project_id") is not None
            and binding["project_id"] != selected_project
        ):
            raise ProjectOnboardingRunError(
                "onboarding_checkout_mismatch: run yoke setup to bind this checkout to the selected project."
            )
        selected_branch = branch or (
            existing["branch"] if existing is not None else BRANCH_LOCAL_CHECKOUT
        )
        validate_branch(selected_branch)
        now = utc_now()
        p = _p(conn)
        saved = read_saved_metadata(existing["metadata_json"]) if existing is not None else {}
        saved.update(metadata)
        saved = update_machine_choices(
            saved,
            machine_id=machine_id,
            checkout_path=checkout_path,
            machine_config_path=machine_config_path,
            row_status=row_status,
            evidence=evidence,
            blocker=blocker,
            note=note,
        )
        if "execution_profile" in metadata:
            saved["profile_facts"] = profile_snapshot(
                project_facts(conn, selected_project)
            )
            row_status = {**row_status, "human-interview": "configured"}
        _upsert_run(
            conn, selected_id, selected_project, selected_branch, github_repo, now
        )
        upsert_default_rows(conn, p, selected_id, selected_branch, now)
        global_updates = [
            {key: value for key, value in values.items() if key not in MACHINE_ROW_IDS}
            for values in (row_status, evidence, blocker, note)
        ]
        apply_row_updates(
            conn,
            p,
            selected_id,
            now,
            row_status=global_updates[0],
            evidence=global_updates[1],
            blocker=global_updates[2],
            note=global_updates[3],
        )
        _set_run_metadata(conn, selected_id, STATUS_NEEDED, saved, now)
        payload = get_run(
            selected_id,
            conn=conn,
            machine_id=machine_id,
            observations=observations,
            project_access=project_access,
        )
        _set_run_metadata(
            conn,
            selected_id,
            payload["summary"]["status"],
            run_metadata(payload, operation=operation, extra=None),
            now,
        )
        conn.execute("RELEASE SAVEPOINT onboarding_update")
    except BaseException:
        conn.execute("ROLLBACK TO SAVEPOINT onboarding_update")
        conn.execute("RELEASE SAVEPOINT onboarding_update")
        raise
    conn.commit()
    payload = get_run(
        selected_id,
        conn=conn,
        machine_id=machine_id,
        observations=observations,
        project_access=project_access,
    )
    return with_operation(payload, operation=operation, resumed=existing is not None)


def _upsert_run(
    conn: Any,
    run_id: str,
    project_id: int | None,
    branch: str,
    github_repo: str | None,
    now: datetime,
) -> None:
    p = _p(conn)
    written = conn.execute(
        "INSERT INTO project_onboarding_runs "
        "(run_id, schema_version, project_id, branch, github_repo, status, "
        "metadata_json, created_at, updated_at) "
        f"VALUES ({', '.join([p] * 9)}) "
        "ON CONFLICT (run_id) DO UPDATE SET "
        "branch = EXCLUDED.branch, "
        "github_repo = COALESCE(EXCLUDED.github_repo, project_onboarding_runs.github_repo), "
        "updated_at = EXCLUDED.updated_at "
        "WHERE project_onboarding_runs.project_id IS NOT DISTINCT FROM EXCLUDED.project_id "
        "RETURNING run_id",
        (
            run_id,
            SCHEMA_VERSION,
            project_id,
            branch,
            github_repo,
            STATUS_NEEDED,
            json_dumps(base_metadata()),
            instant_parameter(conn, now),
            instant_parameter(conn, now),
        ),
    ).fetchone()
    if written is None:
        raise ProjectOnboardingRunError(
            "onboarding_project_mismatch: the run id was claimed by another project; "
            "omit --run-id to resume the selected project."
        )


def _set_run_metadata(
    conn: Any,
    run_id: str,
    status: str,
    metadata: Mapping[str, Any],
    now: datetime,
) -> None:
    p = _p(conn)
    conn.execute(
        "UPDATE project_onboarding_runs "
        f"SET status = {p}, metadata_json = {p}, updated_at = {p} WHERE run_id = {p}",
        (status, json_dumps(metadata), instant_parameter(conn, now), run_id),
    )
