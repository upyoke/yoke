"""Deployment-related done-transition gates.

Deployment evidence is owned by ``deployment_runs`` /
``deployment_run_items`` (plus the legacy ``deploy_stage`` item field
for runless flows). The events ledger is telemetry-only and is not
consulted.
"""

from __future__ import annotations

from typing import Optional, Tuple

from yoke_core.domain import db_backend


def _parent():
    from yoke_core.engines import done_transition as _dt
    return _dt


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _check_deployment_flow_guard(
    item_id: int,
    deploy_flow: str,
    skip_deploy: bool,
    item_project: str,
    old_status: str,
) -> Optional[Tuple[int, str]]:
    """Post-merge deployment flow guard.

    Returns (exit_code, new_status) or None if clear.
    """
    is_internal = deploy_flow.endswith("-internal") if deploy_flow else False
    if not deploy_flow or is_internal:
        return None

    # Distinguish registered flows that lack deployment evidence from
    # values that are not real flow ids.
    from yoke_core.domain.deployment_flow_validator import (
        list_registered_flow_ids,
    )

    with _parent()._connect() as conn:
        registered_flows = list_registered_flow_ids(conn)
    if deploy_flow not in registered_flows:
        print(f"\n=== Deployment flow guard ===")
        print(
            f"Blocked: Item YOK-{item_id} has deployment_flow '{deploy_flow}' "
            f"which is NOT a registered deployment flow."
        )
        if registered_flows:
            print(
                f"Repair items.deployment_flow to one of: "
                f"{', '.join(registered_flows)}."
            )
        else:
            print("No deployment flows are registered. Seed deployment_flows first.")
        return 7, old_status

    if skip_deploy:
        # still requires evidence
        has_evidence = _check_deployment_evidence(item_id)
        if not has_evidence:
            print(f"\n=== Deployment evidence guard ===")
            print(f"Blocked: --skip-deploy passed for YOK-{item_id} but no "
                  "successful deployment evidence found.")
            print(f"\nItem has deployment flow '{deploy_flow}' — cannot transition "
                  "to done without evidence that the deployment pipeline ran "
                  "successfully.")
            print(f"Run '/yoke usher YOK-{item_id}' to deploy first.")
            return 7, old_status
        print(f"Deployment evidence verified for YOK-{item_id}.")
        print("  Skipping live deployment pipeline checks per --skip-deploy.")
        return None

    # Check deployment_runs for run-based evidence
    run_status, run_id = _get_latest_run_status(item_id)

    if run_status:
        if run_status == "succeeded":
            # Check stage consistency
            stage_error = _check_run_stage_consistency(run_id)
            if stage_error:
                return 7, old_status
            # Check blocking QA
            qa_error = _check_run_qa_gates(run_id)
            if qa_error:
                return 7, old_status
            print(f"Deployment flow guard: run succeeded, QA satisfied — proceeding to done.")
            return None
        elif run_status in ("created", "executing"):
            print(f"\n=== Deployment run guard ===")
            print(f"Blocked: Item YOK-{item_id} has a deployment run at "
                  f"status '{run_status}'.")
            print(f"\nThe deployment pipeline has not completed yet.")
            print(f"Wait for the deployment run to finish, or run "
                  f"'/yoke usher YOK-{item_id}' to retry.")
            return 7, old_status
        elif run_status in ("failed", "cancelled"):
            print(f"\n=== Deployment run guard ===")
            print(f"Blocked: Item YOK-{item_id} has a deployment run at "
                  f"status '{run_status}'.")
            print(f"\nThe deployment pipeline did not succeed.")
            print(f"Run '/yoke usher YOK-{item_id}' to create a new "
                  "deployment run.")
            return 7, old_status
        else:
            print(f"Warning: unexpected run status '{run_status}' for "
                  f"YOK-{item_id}, falling back to deploy_stage check.")

    if not run_status:
        # No runs recorded — no deployment evidence.
        print(f"\n=== Deployment evidence guard ===")
        print(f"Blocked: Item YOK-{item_id} has deployment flow "
              f"'{deploy_flow}' but no deployment evidence.")
        print(f"\nThe deployment pipeline was never executed for this item.")
        print(f"Run '/yoke usher YOK-{item_id}' to deploy first.")
        # Set status to release
        _parent()._update_item_direct(
            item_id,
            "status",
            "release",
            env_overrides={"YOKE_STATUS_SOURCE": "done-transition"},
            rebuild_board=False,
        )
        return 7, "release"

    # deploy_stage check for runless deployment evidence.
    if not run_status or run_status != "succeeded":
        deploy_stage = _parent()._query_item_field(item_id, "deploy_stage")
        if deploy_stage == "complete":
            print("Deployment flow guard: deploy_stage=complete — proceeding to done.")
            return None
        # Set to release and redirect
        print(f"\n=== Deployment flow guard ===")
        print(f"Item YOK-{item_id} has deployment flow '{deploy_flow}' "
              f"(deploy_stage='{deploy_stage}').")
        print("Merge completed successfully. Setting status to 'release'.")
        _parent()._update_item_direct(
            item_id,
            "status",
            "release",
            env_overrides={"YOKE_STATUS_SOURCE": "done-transition"},
            rebuild_board=False,
        )
        # Cascade release to reviewed-implementation child tasks
        _cascade_release_to_children(item_id)
        _parent()._rebuild_board_direct()
        print(f"\nNext step: run '/yoke usher YOK-{item_id}' to execute "
              "the deployment pipeline.")
        return 7, "release"

    return None


def _check_deployment_evidence(item_id: int) -> bool:
    """True iff the item's latest deployment run succeeded."""
    with _parent()._connect() as conn:
        p = _p(conn)
        run_row = conn.execute(
            "SELECT dr.status FROM deployment_runs dr "
            "JOIN deployment_run_items dri ON dr.id = dri.run_id "
            f"WHERE dri.item_id = {p} ORDER BY dr.created_at DESC LIMIT 1",
            (item_id,),
        ).fetchone()
        return bool(run_row and run_row[0] == "succeeded")


def _get_latest_run_status(item_id: int) -> Tuple[str, str]:
    """Get the latest deployment run status and ID for an item."""
    with _parent()._connect() as conn:
        row = conn.execute(
            "SELECT dr.id, dr.status FROM deployment_runs dr "
            "JOIN deployment_run_items dri ON dr.id = dri.run_id "
            f"WHERE dri.item_id = {_p(conn)} ORDER BY dr.created_at DESC LIMIT 1",
            (item_id,),
        ).fetchone()
    if not row:
        return "", ""
    return str(row["status"] or ""), str(row["id"] or "")


def _check_run_stage_consistency(run_id: str) -> bool:
    """Check run stage doesn't indicate failure. Returns True if error."""
    if not run_id:
        return False
    with _parent()._connect() as conn:
        row = conn.execute(
            f"SELECT COALESCE(current_stage, '') FROM deployment_runs WHERE id = {_p(conn)}",
            (run_id,),
        ).fetchone()
    if row and str(row[0]).endswith("-failed"):
        stage = row[0]
        print(f"\n=== Deployment stage guard ===")
        print(f"Blocked: Deployment run '{run_id}' has status=succeeded but "
              f"current_stage='{stage}'.")
        print(f"\nThis is a contradictory state — the stage indicates failure.")
        return True
    return False


def _check_run_qa_gates(run_id: str) -> bool:
    """Check blocking QA requirements on run. Returns True if error."""
    if not run_id:
        return False
    with _parent()._connect() as conn:
        rows = conn.execute(
            "SELECT check_name || ' (' || status || ')' FROM deployment_run_qa "
            f"WHERE run_id = {_p(conn)} AND blocking = 1 AND status <> 'passed' "
            "AND status <> 'waived'",
            (run_id,),
        ).fetchall()
    if rows:
        print(f"\n=== Deployment QA guard ===")
        print(f"Blocked: Deployment run '{run_id}' succeeded but blocking "
              "QA checks are unsatisfied:")
        for r in rows:
            print(f"  - {r[0]}")
        print(f"\nSatisfy all blocking QA checks before transitioning to done.")
        return True
    return False


def _cascade_release_to_children(item_id: int) -> None:
    """Cascade release status to reviewed-implementation child tasks."""
    from yoke_core.domain import epic as _epic_domain

    item_type = _parent()._query_item_field(item_id, "type")
    epic_name = str(item_id)
    if item_type != "epic" or not epic_name:
        return
    with _parent()._connect() as conn:
        task_list_output = _epic_domain.task_list(conn, epic_name)
    if not task_list_output:
        return
    for line in task_list_output.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("|")
        if len(parts) < 8:
            continue
        task_num = parts[2].strip()
        task_status = parts[7].strip()
        if task_status == "reviewed-implementation":
            _parent()._update_task_status_direct(
                epic_name,
                task_num,
                "release",
                f"Parent YOK-{item_id} set to release",
                env_overrides={
                    "YOKE_CLAIM_BYPASS": f"done-cascade:YOK-{item_id}",
                },
                no_rebuild=True,
                no_github=False,
                no_derive=False,
            )
            print(f"  Cascaded: task {task_num} (reviewed-implementation -> release)")
