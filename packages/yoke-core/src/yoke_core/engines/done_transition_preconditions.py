"""Done-transition preconditions for the final 'status=done' write.

These four checks run after the deployment-flow guard and before the
status-flip to ``done``. They produce exact rejection-reason strings so
callers and tests can branch precisely.

Contract: ``check_done_preconditions(item_id, deploy_flow, require_plan_verdict)``
returns ``(allowed: bool, reason: str | None)``.

- ``deployed_to`` non-empty for any registered deployment_flow that
  is not ``no-run-delivery`` (``no-run-delivery`` is carved out).
- ``deploy_stage`` non-null for any registered deployment_flow.
- Latest ``deploy_runs`` row for the item is not ``status='failed'``.
- When the pinned workflow requires a planning verdict, a ``shepherd_verdicts`` row exists with
  ``transition='refined_idea_to_planning'`` and verdict in (READY, CAVEATS).
"""

from __future__ import annotations

import sys
from typing import Any, Optional, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.project_identity import render_item_ref


# Documented escape hatch for items that do not have a deploy run. The
# value is recognized by name even when the deployment_flows registry
# does not list it.
NO_RUN_DELIVERY_FLOW = "no-run-delivery"


def _parent():
    from yoke_core.engines import done_transition as _dt
    return _dt


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _is_registered_flow(conn: Any, deploy_flow: str) -> bool:
    """True when ``deploy_flow`` appears in the live deployment_flows table.

    Internal flows (``*-internal``) are deliberately excluded from the
    preconditions surface — they short-circuit out before this gate runs.
    """
    from yoke_core.domain.deployment_flow_validator import (
        list_registered_flow_ids,
    )

    return deploy_flow in list_registered_flow_ids(conn)


def _query_item_scalar(conn: Any, item_id: int, field: str) -> str:
    row = conn.execute(
        f"SELECT {field} FROM items WHERE id = {_p(conn)}", (item_id,),
    ).fetchone()
    if not row:
        return ""
    value = row[0]
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() == "null":
        return ""
    return text


def _latest_run_status(conn: Any, item_id: int) -> str:
    row = conn.execute(
        "SELECT dr.status FROM deployment_runs dr "
        "JOIN deployment_run_items dri ON dr.id = dri.run_id "
        f"WHERE dri.item_id = {_p(conn)} ORDER BY dr.created_at DESC LIMIT 1",
        (item_id,),
    ).fetchone()
    if not row:
        return ""
    return str(row[0] or "")


def _has_refined_idea_to_planning_verdict(
    conn: Any, item_id: int,
) -> bool:
    row = conn.execute(
        "SELECT 1 FROM shepherd_verdicts "
        f"WHERE item = {_p(conn)} AND transition = 'refined_idea_to_planning' "
        "AND verdict IN ('READY', 'CAVEATS') LIMIT 1",
        (f"YOK-{item_id}",),
    ).fetchone()
    return row is not None


def evaluate_done_preconditions(
    conn: Any,
    item_id: int,
    deploy_flow: str,
    require_plan_verdict: bool,
) -> Tuple[bool, Optional[str]]:
    """Run all four preconditions over *conn*; return ``(allowed, reason)``.

    Connection-based core shared by the server-side
    ``done_transition.done_preconditions`` relay handler. The first failing
    check short-circuits with an exact reason string. Empty / null / internal
    deployment flows skip the deployment-shape checks (deployed_to and
    deploy_stage) — those flows do not deploy through the registered
    pipeline. The failed-deploy_run check still applies whenever a deploy_run
    exists.
    """
    is_internal = bool(deploy_flow) and deploy_flow.endswith("-internal")
    is_no_run_delivery = deploy_flow == NO_RUN_DELIVERY_FLOW
    registered = bool(deploy_flow) and not is_internal and (
        is_no_run_delivery or _is_registered_flow(conn, deploy_flow)
    )

    # deployed_to non-empty for any registered, non-bypass flow.
    if registered and not is_no_run_delivery:
        deployed_to = _query_item_scalar(conn, item_id, "deployed_to")
        if not deployed_to:
            return False, (
                f"deployed_to is empty for deployment_flow={deploy_flow}"
            )

    # deploy_stage non-null for any registered flow (incl. no-run-delivery).
    if registered:
        deploy_stage = _query_item_scalar(conn, item_id, "deploy_stage")
        if not deploy_stage:
            return False, (
                f"deploy_stage is null for deployment_flow={deploy_flow}"
            )

    # Latest deploy_run for the item must not be failed.
    run_status = _latest_run_status(conn, item_id)
    if run_status == "failed":
        return False, (
            f"latest deploy_run for {render_item_ref(conn, item_id)} has status=failed"
        )

    # Planning workflows require their refinement verdict in history.
    if require_plan_verdict:
        if not _has_refined_idea_to_planning_verdict(conn, item_id):
            return False, (
                f"{render_item_ref(conn, item_id)} missing required "
                "refined_idea_to_planning READY/CAVEATS verdict"
            )

    return True, None


def check_done_preconditions(
    item_id: int,
    deploy_flow: str,
    require_plan_verdict: bool,
) -> Tuple[bool, Optional[str]]:
    """Run all four preconditions through the connected transport.

    Relays ``done_transition.done_preconditions`` so the precondition bundle
    runs over an https control plane as well as a local Postgres connection,
    then returns its ``(allowed, reason)`` verdict verbatim. A read failure
    raises, aborting the transition exactly as the inline ``connect()`` did
    on a DB-level failure — this gate never degrades to "allowed".
    """
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import (
        call_dispatcher,
    )

    resp = call_dispatcher(
        function_id="done_transition.done_preconditions",
        target=TargetRef(kind="item", item_id=int(item_id)),
        payload={
            "deploy_flow": deploy_flow,
            "require_plan_verdict": require_plan_verdict,
        },
    )
    if not resp.success:
        message = resp.error.message if resp.error else "unknown error"
        raise RuntimeError(f"done preconditions read failed: {message}")
    data = resp.result or {}
    return bool(data.get("allowed")), data.get("reason")


def enforce_preconditions(
    item_id: int,
    deploy_flow: str,
    require_plan_verdict: bool,
) -> Optional[str]:
    """Runner hook: emit the guard banner on failure, return reason or None."""
    allowed, reason = check_done_preconditions(
        item_id,
        deploy_flow,
        require_plan_verdict,
    )
    if allowed:
        return None
    print("\n=== Done preconditions guard ===", file=sys.stderr)
    print(f"Blocked: {reason}", file=sys.stderr)
    return reason
