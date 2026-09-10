"""Project authorization for hosted coordination-claim recovery."""

from __future__ import annotations

from runtime.api.domain.test_yoke_function_permissions import _conn, _entry
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.actor_permissions import (
    PERM_CLAIMS_RELEASE,
    ROLE_OWNER,
    grant_actor_project_role,
)
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.yoke_function_permissions import check_dispatch_permission


def test_coordination_operator_release_is_project_scoped() -> None:
    conn = _conn()
    try:
        actor_id = seed_human_actor(conn)
        yoke_id = resolve_project_id(conn, "yoke")
        grant_actor_project_role(
            conn,
            actor_id=actor_id,
            project_id=yoke_id,
            role_name=ROLE_OWNER,
            granted_by_actor_id=actor_id,
        )
        entry = _entry("claims.coordination_claim.operator_release")

        def request(project: str) -> FunctionCallRequest:
            return FunctionCallRequest(
                function=entry.function_id,
                actor=ActorContext(actor_id=str(actor_id), session_id=""),
                target=TargetRef(kind="global"),
                payload={
                    "project_id": project,
                    "key": f"DEPLOY:{project}",
                    "claim_id": 42,
                    "holder_session_id": "holder",
                    "reason": "reviewed stranded holder",
                },
            )

        allowed = check_dispatch_permission(conn, entry, request("yoke"))
        denied = check_dispatch_permission(conn, entry, request("externalwebapp"))

        assert allowed.error is None
        assert allowed.permission_key == PERM_CLAIMS_RELEASE
        assert denied.error is not None
        assert denied.error.error is not None
        assert denied.error.error.code == "permission_denied"
    finally:
        conn.close()
