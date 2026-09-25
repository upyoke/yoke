"""Disabled actor authority, credential retirement, and recovery."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.actor_permissions import (
    PERM_PROJECT_RENDER_READ,
    ROLE_DEPLOYMENT_CI,
    ROLE_INFRASTRUCTURE_CI,
    grant_actor_project_role,
    grant_actor_org_role,
    seed_roles_and_permissions,
)
from yoke_core.domain.actor_permission_checks import permission_decision
from yoke_core.domain.actor_state import (
    ActorDisabledError,
    ActorStateRefused,
    set_actor_enabled,
)
from yoke_core.domain.actors import (
    SYSTEM_COMPONENT_YOKE_CORE,
    seed_human_actor,
    seed_system_actor,
)
from yoke_core.domain.api_tokens import (
    TokenActorDisabled,
    TokenRevoked,
    mint_token,
    revoke_token,
    verify_token,
)
from yoke_core.domain.control_plane_authority import resolve_control_plane_org_id
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.decision_request_authority import human_role_holders
from yoke_core.domain.machine_credentials import register_with_credential
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.project_seed_test_helpers import seed_project_identities
from yoke_core.domain.web_sessions import (
    WebSessionRevoked,
    mint_web_session,
    verify_web_session,
)
from yoke_core.domain.yoke_function_permissions import check_dispatch_permission


def _people(conn):
    seed_roles_and_permissions(conn)
    org_id = resolve_control_plane_org_id(conn)
    caller = seed_human_actor(conn, "Admin")
    subject = seed_human_actor(conn, "Member")
    grant_actor_org_role(conn, actor_id=caller, org_id=org_id, role_name="admin")
    grant_actor_org_role(conn, actor_id=subject, org_id=org_id, role_name="admin")
    return caller, subject, org_id


def _keyless_request(actor_id):
    return FunctionCallRequest(
        function="actors.state.set",
        actor=ActorContext(actor_id=str(actor_id), session_id=""),
        target=TargetRef(kind="global"),
        payload={"actor_id": actor_id, "enabled": True},
    )


def test_disable_retires_personal_and_machine_keys_and_blocks_browser_and_keyless_actor(
    test_db,
):
    caller, subject, org_id = _people(test_db)
    personal = mint_token(test_db, actor_id=subject, name="personal")
    machine_id = str(uuid4())
    _, _, machine = register_with_credential(
        test_db,
        machine_id=machine_id,
        name="Test machine",
        actor_id=subject,
        now=iso8601_now(),
    )
    browser = mint_web_session(test_db, actor_id=subject)
    entry = SimpleNamespace(
        function_id="actors.state.set", version="v1", side_effects=("actors_update",)
    )
    assert (
        check_dispatch_permission(test_db, entry, _keyless_request(subject)).error
        is None
    )

    assert (
        set_actor_enabled(
            test_db,
            actor_id=subject,
            caller_actor_id=caller,
            enabled=False,
            now=iso8601_now(),
        )
        == 2
    )
    assert (
        check_dispatch_permission(
            test_db, entry, _keyless_request(subject)
        ).error.error.code
        == "actor_disabled"
    )
    assert subject not in human_role_holders(
        test_db, scope_kind="org", scope_id=org_id, role_name="admin"
    )
    with pytest.raises(ActorDisabledError):
        verify_web_session(test_db, browser.raw_token)
    with pytest.raises(TokenActorDisabled):
        verify_token(test_db, personal.raw_token)
    with pytest.raises(TokenActorDisabled):
        verify_token(test_db, machine.token)
    with pytest.raises(ActorDisabledError):
        mint_token(test_db, actor_id=subject, name="blocked")
    with pytest.raises(ActorDisabledError):
        mint_web_session(test_db, actor_id=subject)
    with pytest.raises(ActorDisabledError):
        register_with_credential(
            test_db,
            machine_id=machine_id,
            name="Test machine",
            actor_id=subject,
            now=iso8601_now(),
        )
    audit = test_db.execute(
        "SELECT COUNT(*) FROM api_token_audit WHERE actor_id = %s "
        "AND event_type = 'revoked' AND outcome = 'actor_disabled'",
        (subject,),
    ).fetchone()[0]
    assert audit == 2

    set_actor_enabled(
        test_db,
        actor_id=subject,
        caller_actor_id=caller,
        enabled=True,
        now=iso8601_now(),
    )
    assert (
        check_dispatch_permission(test_db, entry, _keyless_request(subject)).error
        is None
    )
    assert subject in human_role_holders(
        test_db, scope_kind="org", scope_id=org_id, role_name="admin"
    )
    with pytest.raises(TokenRevoked):
        verify_token(test_db, personal.raw_token)
    with pytest.raises(WebSessionRevoked):
        verify_web_session(test_db, browser.raw_token)
    assert mint_web_session(test_db, actor_id=subject).actor_id == subject


def test_disable_rejects_self_core_and_last_active_admin(test_db):
    caller, subject, _ = _people(test_db)
    system = seed_system_actor(test_db, SYSTEM_COMPONENT_YOKE_CORE)
    with pytest.raises(ActorStateRefused, match="own actor"):
        set_actor_enabled(
            test_db,
            actor_id=caller,
            caller_actor_id=caller,
            enabled=False,
            now=iso8601_now(),
        )
    with pytest.raises(ActorStateRefused, match="canonical core actor"):
        set_actor_enabled(
            test_db,
            actor_id=system,
            caller_actor_id=caller,
            enabled=False,
            now=iso8601_now(),
            confirm_system_retirement=True,
        )
    set_actor_enabled(
        test_db,
        actor_id=caller,
        caller_actor_id=subject,
        enabled=False,
        now=iso8601_now(),
    )
    with pytest.raises(ActorStateRefused, match="last active admin"):
        set_actor_enabled(
            test_db,
            actor_id=subject,
            caller_actor_id=caller,
            enabled=False,
            now=iso8601_now(),
        )


def test_obsolete_system_actor_requires_confirmation_and_loses_authority(test_db):
    caller, _, _ = _people(test_db)
    seed_project_identities(test_db)
    project_id = resolve_project_id(test_db, "yoke")
    system = seed_system_actor(test_db, "retired-preview-worker")
    grant_actor_project_role(
        test_db,
        actor_id=system,
        project_id=project_id,
        role_name=ROLE_INFRASTRUCTURE_CI,
    )
    token = mint_token(test_db, actor_id=system, name="obsolete worker")
    assert permission_decision(
        test_db,
        actor_id=system,
        project_id=project_id,
        permission_key=PERM_PROJECT_RENDER_READ,
    ).allowed
    with pytest.raises(ActorStateRefused, match="--confirm-system-retirement"):
        set_actor_enabled(
            test_db,
            actor_id=system,
            caller_actor_id=caller,
            enabled=False,
            now=iso8601_now(),
        )
    assert (
        set_actor_enabled(
            test_db,
            actor_id=system,
            caller_actor_id=caller,
            enabled=False,
            now=iso8601_now(),
            confirm_system_retirement=True,
        )
        == 1
    )
    assert not permission_decision(
        test_db,
        actor_id=system,
        project_id=project_id,
        permission_key=PERM_PROJECT_RENDER_READ,
    ).allowed
    with pytest.raises(TokenActorDisabled):
        verify_token(test_db, token.raw_token)
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM api_token_audit WHERE actor_id = %s "
            "AND event_type = 'revoked' AND outcome = 'actor_disabled'",
            (system,),
        ).fetchone()[0]
        == 1
    )
    set_actor_enabled(
        test_db,
        actor_id=system,
        caller_actor_id=caller,
        enabled=True,
        now=iso8601_now(),
    )
    with pytest.raises(TokenRevoked):
        verify_token(test_db, token.raw_token)


def test_live_deployment_actor_requires_credential_retirement(test_db):
    caller, _, _ = _people(test_db)
    seed_project_identities(test_db)
    project_id = resolve_project_id(test_db, "yoke")
    system = seed_system_actor(test_db, "release-bridge-test")
    grant_actor_project_role(
        test_db,
        actor_id=system,
        project_id=project_id,
        role_name=ROLE_DEPLOYMENT_CI,
    )
    token = mint_token(test_db, actor_id=system, name="serving deployment")
    with pytest.raises(ActorStateRefused, match="active deployment credential"):
        set_actor_enabled(
            test_db,
            actor_id=system,
            caller_actor_id=caller,
            enabled=False,
            now=iso8601_now(),
            confirm_system_retirement=True,
        )
    revoke_token(test_db, token_id=token.token_id)
    assert (
        set_actor_enabled(
            test_db,
            actor_id=system,
            caller_actor_id=caller,
            enabled=False,
            now=iso8601_now(),
            confirm_system_retirement=True,
        )
        == 0
    )
