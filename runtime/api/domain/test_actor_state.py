"""Disabled actor authority, credential retirement, and recovery."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, TargetRef
from yoke_core.domain.actor_permissions import (
    grant_actor_org_role,
    seed_roles_and_permissions,
)
from yoke_core.domain.actor_state import (
    ActorDisabledError,
    ActorStateRefused,
    set_actor_enabled,
)
from yoke_core.domain.actors import seed_human_actor, seed_system_actor
from yoke_core.domain.api_tokens import TokenActorDisabled, TokenRevoked, mint_token, verify_token
from yoke_core.domain.control_plane_authority import resolve_control_plane_org_id
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.machine_credentials import register_with_credential
from yoke_core.domain.web_sessions import WebSessionRevoked, mint_web_session, verify_web_session
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


def test_disable_retires_personal_and_machine_keys_and_blocks_browser_and_keyless_actor(test_db):
    caller, subject, _ = _people(test_db)
    personal = mint_token(test_db, actor_id=subject, name="personal")
    machine_id = str(uuid4())
    _, _, machine = register_with_credential(
        test_db, machine_id=machine_id, name="Test machine",
        actor_id=subject, now=iso8601_now(),
    )
    browser = mint_web_session(test_db, actor_id=subject)
    entry = SimpleNamespace(
        function_id="actors.state.set", version="v1", side_effects=("actors_update",)
    )
    assert check_dispatch_permission(test_db, entry, _keyless_request(subject)).error is None

    assert set_actor_enabled(
        test_db, actor_id=subject, caller_actor_id=caller,
        enabled=False, now=iso8601_now(),
    ) == 2
    assert check_dispatch_permission(test_db, entry, _keyless_request(subject)).error.code == "actor_disabled"
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
            test_db, machine_id=machine_id, name="Test machine",
            actor_id=subject, now=iso8601_now(),
        )
    audit = test_db.execute(
        "SELECT COUNT(*) FROM api_token_audit WHERE actor_id = %s "
        "AND event_type = 'revoked' AND outcome = 'actor_disabled'",
        (subject,),
    ).fetchone()[0]
    assert audit == 2

    set_actor_enabled(
        test_db, actor_id=subject, caller_actor_id=caller,
        enabled=True, now=iso8601_now(),
    )
    assert check_dispatch_permission(test_db, entry, _keyless_request(subject)).error is None
    with pytest.raises(TokenRevoked):
        verify_token(test_db, personal.raw_token)
    with pytest.raises(WebSessionRevoked):
        verify_web_session(test_db, browser.raw_token)
    assert mint_web_session(test_db, actor_id=subject).actor_id == subject


def test_disable_rejects_self_system_and_last_active_admin(test_db):
    caller, subject, org_id = _people(test_db)
    system = seed_system_actor(test_db, "actor-state-critical")
    with pytest.raises(ActorStateRefused, match="own actor"):
        set_actor_enabled(
            test_db, actor_id=caller, caller_actor_id=caller,
            enabled=False, now=iso8601_now(),
        )
    with pytest.raises(ActorStateRefused, match="system-critical"):
        set_actor_enabled(
            test_db, actor_id=system, caller_actor_id=caller,
            enabled=False, now=iso8601_now(),
        )
    set_actor_enabled(
        test_db, actor_id=caller, caller_actor_id=subject,
        enabled=False, now=iso8601_now(),
    )
    with pytest.raises(ActorStateRefused, match="last active admin"):
        set_actor_enabled(
            test_db, actor_id=subject, caller_actor_id=caller,
            enabled=False, now=iso8601_now(),
        )
