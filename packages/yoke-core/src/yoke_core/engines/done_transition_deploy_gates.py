"""Deployment-related done-transition gates.

Deployment evidence is owned by ``deployment_runs`` /
``deployment_run_items`` (plus the legacy ``deploy_stage`` item field
for runless flows). The events ledger is telemetry-only and is not
consulted.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher


def _parent():
    from yoke_core.engines import done_transition as _dt

    return _dt


def _relay_read(
    function_id: str, target: TargetRef, payload: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Relay a deployment-guard read, raising on an unavailable read.

    These guards previously opened a bare ``_parent()._connect()`` that
    crashed on a DB-level failure (the item never reached done). Preserving
    that fail-closed behavior, a refused relay or transport error raises so
    the transition aborts rather than proceeding on unread deployment
    evidence. The reads run over an https control plane as well as a local
    Postgres connection.
    """
    resp = call_dispatcher(
        function_id=function_id, target=target, payload=payload or {}
    )
    if not resp.success:
        message = resp.error.message if resp.error else "unknown error"
        raise RuntimeError(f"{function_id} read failed: {message}")
    return resp.result or {}


def _check_deployment_flow_guard(
    item_id: int,
    deploy_flow: str,
    skip_deploy: bool,
    item_project: str,
    old_status: str,
    delivery_stage_id: str | None,
    *,
    item_ref: str,
) -> Optional[Tuple[int, str]]:
    """Post-merge deployment flow guard.

    ``item_ref`` is the project-aware public ref resolved once (server-side)
    by the caller, so the guard renders its block narratives without opening a
    local connection on this read path.

    Returns (exit_code, new_status) or None if clear.
    """
    is_internal = deploy_flow.endswith("-internal") if deploy_flow else False
    if not deploy_flow or is_internal:
        return None

    # Distinguish registered flows that lack deployment evidence from
    # values that are not real flow ids. The registered-flow list relays so
    # the guard runs over an https control plane as well as locally.
    registered_flows = _relay_read(
        "done_transition.registered_flow_ids", TargetRef(kind="global")
    ).get("flow_ids", [])
    if deploy_flow not in registered_flows:
        print("\n=== Deployment flow guard ===")
        print(
            f"Blocked: Item {item_ref} has deployment_flow '{deploy_flow}' "
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
            print("\n=== Deployment evidence guard ===")
            print(
                f"Blocked: --skip-deploy passed for {item_ref} but no "
                "successful deployment evidence found."
            )
            print(
                f"\nItem has deployment flow '{deploy_flow}' — cannot transition "
                "to done without evidence that the deployment pipeline ran "
                "successfully."
            )
            print(f"Run '/yoke usher {item_ref}' to deploy first.")
            return 7, old_status
        print(f"Deployment evidence verified for {item_ref}.")
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
            print(
                "Deployment flow guard: run succeeded, QA satisfied — proceeding to done."
            )
            return None
        elif run_status in ("created", "executing"):
            print("\n=== Deployment run guard ===")
            print(
                f"Blocked: Item {item_ref} has a deployment run at "
                f"status '{run_status}'."
            )
            print("\nThe deployment pipeline has not completed yet.")
            print(
                f"Wait for the deployment run to finish, or run "
                f"'/yoke usher {item_ref}' to retry."
            )
            return 7, old_status
        elif run_status in ("failed", "cancelled"):
            print("\n=== Deployment run guard ===")
            print(
                f"Blocked: Item {item_ref} has a deployment run at "
                f"status '{run_status}'."
            )
            print("\nThe deployment pipeline did not succeed.")
            print(f"Run '/yoke usher {item_ref}' to create a new deployment run.")
            return 7, old_status
        else:
            print(
                f"Warning: unexpected run status '{run_status}' for "
                f"{item_ref}, falling back to deploy_stage check."
            )

    if not run_status:
        # No runs recorded — no deployment evidence.
        print("\n=== Deployment evidence guard ===")
        print(
            f"Blocked: Item {item_ref} has deployment flow "
            f"'{deploy_flow}' but no deployment evidence."
        )
        print("\nThe deployment pipeline was never executed for this item.")
        print(f"Run '/yoke usher {item_ref}' to deploy first.")
        return _redirect_to_delivery_stage(
            item_id, old_status, delivery_stage_id, item_ref=item_ref
        )

    # deploy_stage check for runless deployment evidence.
    if not run_status or run_status != "succeeded":
        deploy_stage = _parent()._query_item_field(item_id, "deploy_stage")
        if deploy_stage == "complete":
            print("Deployment flow guard: deploy_stage=complete — proceeding to done.")
            return None
        print("\n=== Deployment flow guard ===")
        print(
            f"Item {item_ref} has deployment flow '{deploy_flow}' "
            f"(deploy_stage='{deploy_stage}')."
        )
        return _redirect_to_delivery_stage(
            item_id, old_status, delivery_stage_id, item_ref=item_ref
        )

    return None


def _redirect_to_delivery_stage(
    item_id: int,
    old_status: str,
    delivery_stage_id: str | None,
    *,
    item_ref: str,
) -> Tuple[int, str]:
    """Move to the pinned definition's delivery stage when it declares one.

    ``item_ref`` is the caller's already-resolved public ref, so the redirect
    narrative renders without opening a local connection.
    """
    if delivery_stage_id is None:
        return 7, old_status
    print(f"Merge completed successfully. Setting status to '{delivery_stage_id}'.")
    _parent()._update_item_direct(
        item_id,
        "status",
        delivery_stage_id,
        env_overrides={"YOKE_STATUS_SOURCE": "done-transition"},
        rebuild_board=False,
        item_ref=item_ref,
    )
    _parent()._rebuild_board_direct()
    print(
        f"\nNext step: run '/yoke usher {item_ref}' to execute "
        "the deployment pipeline."
    )
    return 7, delivery_stage_id


def _check_deployment_evidence(item_id: int) -> bool:
    """True iff the item's latest deployment run succeeded."""
    data = _relay_read(
        "done_transition.latest_deployment_run",
        TargetRef(kind="item", item_id=int(item_id)),
    )
    return data.get("status") == "succeeded"


def _get_latest_run_status(item_id: int) -> Tuple[str, str]:
    """Get the latest deployment run status and ID for an item."""
    data = _relay_read(
        "done_transition.latest_deployment_run",
        TargetRef(kind="item", item_id=int(item_id)),
    )
    return str(data.get("status") or ""), str(data.get("run_id") or "")


def _check_run_stage_consistency(run_id: str) -> bool:
    """Check run stage doesn't indicate failure. Returns True if error."""
    if not run_id:
        return False
    stage = _relay_read(
        "done_transition.run_stage",
        TargetRef(kind="global"),
        {"run_id": run_id},
    ).get("current_stage", "")
    if stage.endswith("-failed"):
        print("\n=== Deployment stage guard ===")
        print(
            f"Blocked: Deployment run '{run_id}' has status=succeeded but "
            f"current_stage='{stage}'."
        )
        print("\nThis is a contradictory state — the stage indicates failure.")
        return True
    return False


def _check_run_qa_gates(run_id: str) -> bool:
    """Check blocking QA requirements on run. Returns True if error."""
    if not run_id:
        return False
    blocking = _relay_read(
        "done_transition.run_blocking_qa",
        TargetRef(kind="global"),
        {"run_id": run_id},
    ).get("blocking", [])
    if blocking:
        print("\n=== Deployment QA guard ===")
        print(
            f"Blocked: Deployment run '{run_id}' succeeded but blocking "
            "QA checks are unsatisfied:"
        )
        for check in blocking:
            print(f"  - {check}")
        print("\nSatisfy all blocking QA checks before transitioning to done.")
        return True
    return False
