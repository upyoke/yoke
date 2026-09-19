"""The release identity may attribute its own pin commit, and nothing more.

Recording release output is a control-plane write reached from a CI runner,
which has no harness session and holds only a scoped project token. Both of
those facts have to be declared, and neither is the default: mutating
functions require an ambient session, and ``deployment_runs.*`` authorizes on
org administration that this identity must never hold.

The pairing is what these checks hold down. Declaring the session opt-out
without the authorization carve-out leaves the bridge refused; granting the
carve-out too widely would hand a release token the rest of the deployment
surface. So one check proves the grant reaches exactly this write, and its
neighbour proves the identity still cannot compose, admit to, or terminate a
run.
"""

from __future__ import annotations

import sqlite3

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.actor_permissions import (
    PERM_ORG_ADMIN,
    PERM_PROJECT_ADMIN,
    PERM_RELEASE_OUTPUT_RECORD,
    ROLE_DEPLOYMENT_CI,
    grant_actor_project_role,
    seed_roles_and_permissions,
)
from yoke_core.domain.auth_schema import create_auth_tables
from yoke_core.domain.org_schema import seed_default_org
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.project_seed_test_helpers import seed_project_identities
from yoke_core.domain.schema_init_actor_path_claim_tables import (
    create_actor_identity_tables,
)
from yoke_core.domain.schema_init_tables import create_core_tables
from yoke_core.domain.yoke_function_permissions import check_dispatch_permission
from yoke_core.domain.yoke_function_registry import RegistryEntry

RECORD = "deployment_runs.release_output.record"
PROJECT_SLUG = "externalwebapp"


class EmptyModel(BaseModel):
    pass


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    create_core_tables(conn)
    seed_project_identities(conn)
    create_actor_identity_tables(conn)
    create_auth_tables(conn)
    seed_default_org(conn)
    seed_roles_and_permissions(conn)
    return conn


def _release_actor(conn: sqlite3.Connection) -> int:
    cursor = conn.execute(
        "INSERT INTO actors (kind, created_at) VALUES ('human', '2026-01-01T00:00:00Z')"
    )
    conn.commit()
    actor_id = int(cursor.lastrowid)
    grant_actor_project_role(
        conn,
        actor_id=actor_id,
        project_id=int(resolve_project_id(conn, PROJECT_SLUG)),
        role_name=ROLE_DEPLOYMENT_CI,
    )
    return actor_id


def _entry(function_id: str) -> RegistryEntry:
    return RegistryEntry(
        function_id=function_id,
        handler=lambda _request: None,
        request_model=EmptyModel,
        response_model=EmptyModel,
        stability="stable",
        owner_module=__name__,
        target_kinds=("global",),
        side_effects=("deployment_runs_update",),
        emitted_event_names=(),
        guardrails=(),
        adapter_status="live",
    )


def _request(actor_id: int, function_id: str) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id=str(actor_id), session_id="release-bridge"),
        target=TargetRef(kind="global", project_id=None),
        payload={"project": PROJECT_SLUG},
    )


def test_the_release_identity_may_record_the_commit_its_promotion_produced() -> None:
    """Without this carve-out the bridge is refused and every pin goes unattributed."""
    conn = _conn()
    try:
        actor_id = _release_actor(conn)

        decision = check_dispatch_permission(
            conn, _entry(RECORD), _request(actor_id, RECORD)
        )

        assert decision.error is None
        assert decision.permission_key == PERM_RELEASE_OUTPUT_RECORD
    finally:
        conn.close()


def test_the_release_identity_reaches_no_other_deployment_run_write() -> None:
    """The carve-out is one write, not a door into the deployment surface."""
    conn = _conn()
    try:
        actor_id = _release_actor(conn)

        for function_id in (
            "deployment_runs.create",
            "deployment_runs.add_item",
            "deployment_runs.validate_composition",
            "deployment_runs.terminalize",
            "deployment_runs.carried_work.repair",
        ):
            decision = check_dispatch_permission(
                conn, _entry(function_id), _request(actor_id, function_id)
            )
            assert decision.error is not None, function_id
            # Which administrative key each one demands differs; what matters
            # is that none of them accepts the narrow release-output grant.
            assert decision.permission_key in {
                PERM_ORG_ADMIN,
                PERM_PROJECT_ADMIN,
            }, function_id
            assert decision.permission_key != PERM_RELEASE_OUTPUT_RECORD
    finally:
        conn.close()


def test_the_registered_write_declares_it_needs_no_harness_session() -> None:
    """A CI runner has no session and never will; the token is the identity.

    Read from the live registry rather than restated, so the declaration and
    the reason it exists cannot drift apart.
    """
    from yoke_core.domain import yoke_function_registry
    from yoke_core.domain.handlers import __init_register__ as init_register

    init_register.register_all_handlers()
    entry = yoke_function_registry.lookup(RECORD)

    assert entry is not None
    assert entry.ambient_session_required is False
    assert entry.claim_required_kind is None
