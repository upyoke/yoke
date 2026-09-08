"""Hand a completed release pair to the session that may actually deploy it.

Deploy authority is a coordination claim, not a property of whoever happened
to merge last. The merging session holds its item's work claim and nothing
else, so it cannot execute the run it just completed, and giving it that
power to close the loop would put deploy authority in every worker — the one
thing this must not do.

So the loop closes by addressing the authority instead of assuming it. The
project's ``DEPLOY:<slug>`` holder is the driver already authorized for this
project's release, and a durable Fleet message reaches it whether it is mid
turn, idle, or yet to resume. When nothing holds the lock the message goes to
the project's steering seat, which is who decides to take it.

The hand-off is keyed on the run and the exact commit, so it survives being
attempted more times than it should be. A close-out that crashes and re-runs,
and every member of a pair whose merges race, all send the same key: the
message service deduplicates it, and one completed pair produces one
hand-off. A key that included the sending item or a timestamp would produce
one message per attempt, which is how an operator learns to ignore them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from yoke_contracts.api.function_call import ActorContext, TargetRef
from yoke_contracts.session_control.recipient_selector import (
    STEERING_SCOPE_PROJECT_KEY,
)
from yoke_core.domain.coordination_claims import active_claim
from yoke_core.domain.work_claim_targets import make_deploy_serialization_target


#: Written where the recipient could not be resolved to a live driver at all.
RECIPIENT_STEERING = "steering"

#: Stands in when this machine cannot resolve its own admin connection, so
#: the recipe still teaches the shape rather than naming a wrong universe.
CONTROL_PLANE_ENV_PLACEHOLDER = "<control-plane>-db-admin"


@dataclass(frozen=True)
class HandoffResult:
    """Who was told the prepared run is ready, and under which message."""

    recipient: str
    message_id: Optional[str]
    delivered: bool


def _control_plane_admin_env() -> str:
    """The admin connection holding the run row, or "" when unresolvable.

    ``--env`` names the CONTROL PLANE the run lives on, never the project
    being released or the environment being deployed to: one control plane
    serves every target, and a label built from either of those names a
    connection that does not exist. The active connection is the one the run
    row was just written through, so its own admin sibling is the answer;
    an env that is already the admin side is used as-is.
    """
    from yoke_contracts.machine_config.schema import (
        DB_ADMIN_ENV_SUFFIX,
        same_universe_db_admin_env,
    )

    try:
        from yoke_core.domain import machine_config

        active = str(machine_config.active_env() or "").strip()
        if active.endswith(DB_ADMIN_ENV_SUFFIX):
            return active
        return same_universe_db_admin_env(machine_config.load_config(), active)
    except Exception:  # noqa: BLE001 - an unresolvable pairing costs the name
        return ""


def _execute_command(run_id: str) -> str:
    """The execute recipe, naming the real connection when one resolves."""
    env = _control_plane_admin_env() or CONTROL_PLANE_ENV_PLACEHOLDER
    return f"yoke --env {env} watch deploy -- {run_id}"


def compose_handoff_body(
    *,
    project_slug: str,
    run_id: str,
    release_lineage: str,
) -> str:
    """Render the hand-off an authorized driver can act on without lookups."""
    return (
        f"Prepared deployment run {run_id} for project {project_slug} is "
        f"ready: its coordinated pair has fully merged and the run now names "
        f"release lineage {release_lineage}.\n\n"
        f"You hold the deploy authority for this project. Execute it with:\n"
        f"  {_execute_command(run_id)}\n\n"
        f"Nothing has been deployed. The run stays in 'created' until you "
        f"execute it, and re-reading it is "
        f"`yoke deployment-runs get {run_id}`."
    )


def _deploy_lock_holder(conn: Any, project_id: int, slug: str) -> Optional[str]:
    claim = active_claim(conn, make_deploy_serialization_target(project_id, slug))
    if claim is None:
        return None
    holder = str(claim.session_id or "").strip()
    return holder or None


def hand_off_prepared_run(
    conn: Any,
    *,
    run_id: str,
    release_lineage: str,
    project: tuple[int, str],
    session_id: Optional[str] = None,
) -> HandoffResult:
    """Tell the project's deploy authority that *run_id* is ready to execute."""
    project_id, slug = project
    body = compose_handoff_body(
        project_slug=slug,
        run_id=run_id,
        release_lineage=release_lineage,
    )
    holder = _deploy_lock_holder(conn, project_id, slug)
    if holder:
        selector: dict[str, Any] = {"session_ids": [holder]}
        recipient = holder
    else:
        selector = {
            "steering": True,
            "steering_scope": {STEERING_SCOPE_PROJECT_KEY: project_id},
        }
        recipient = RECIPIENT_STEERING

    from yoke_core.api.service_client_structured_api_adapter import (
        call_dispatcher,
    )

    caller = (session_id or "").strip()
    response = call_dispatcher(
        function_id="session_control.message.send",
        target=TargetRef(kind="global"),
        payload={
            "selector": selector,
            "body": body,
            "idempotency_key": (
                f"prepared-run-ready:{run_id}:{release_lineage}"
            ),
        },
        actor=ActorContext(session_id=caller) if caller else None,
    )
    if not response.success:
        return HandoffResult(
            recipient=recipient,
            message_id=None,
            delivered=False,
        )
    result = getattr(response, "result", None) or {}
    return HandoffResult(
        recipient=recipient,
        message_id=str(result.get("message_id") or "") or None,
        delivered=True,
    )


__all__ = [
    "CONTROL_PLANE_ENV_PLACEHOLDER",
    "RECIPIENT_STEERING",
    "HandoffResult",
    "compose_handoff_body",
    "hand_off_prepared_run",
]
