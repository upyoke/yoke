"""A coordination claim names its own project when the caller cannot.

Releasing a hold by the row id its acquire handed back, and listing the holds
of one session, both address real tenant rows without naming a project. The
permission check still runs against the project those rows record — this only
supplies the target the check needs, so ownership and tenancy are unchanged.
"""

from __future__ import annotations

from runtime.api.domain.coordination_claim_project_authority_test_support import (
    _project_owner as _project_owner,
    _qa_host_claim as _qa_host_claim,
    _session as _session,
    conn as conn,
)


from typing import Any

import pytest
from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.coordination_claim_keys import (
    CoordinationKeyError,
    key_for_target,
    target_for_key,
)
from yoke_core.domain.function_target_resolution import resolve_project_context
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.work_claim_targets import (
    TARGET_KIND_DEPLOY_SERIALIZATION,
    WorkClaimTarget,
)
from yoke_core.domain.yoke_function_permissions import check_dispatch_permission
from yoke_core.domain.yoke_function_registry import RegistryEntry


class EmptyModel(BaseModel):
    pass


def _entry(function_id: str) -> RegistryEntry:
    return RegistryEntry(
        function_id=function_id,
        handler=lambda _request: None,
        request_model=EmptyModel,
        response_model=EmptyModel,
        stability="stable",
        owner_module=__name__,
        target_kinds=("global",),
        side_effects=("db_write",),
        emitted_event_names=(),
        guardrails=(),
        adapter_status="live",
    )


def _migration_claim(conn: Any, *, project: str, session_id: str) -> int:
    """Insert the row an acquire writes, built by the production constructor.

    The scope is what the resolver reads, so it is built through
    ``target_for_key`` rather than hand-shaped here.
    """
    identity = resolve_project_id(conn, project)
    target = target_for_key("LIVE_DB_MIGRATION:core", project_id=identity, item_id=7)
    cur = conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, scope, claimed_at, last_heartbeat) "
        "VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (
            session_id,
            target.kind,
            target.scope_json(),
            "2026-09-15T00:00:00Z",
            "2026-09-15T00:00:00Z",
        ),
    )
    claim_id = int(cur.fetchone()[0])
    conn.commit()
    return claim_id


def _release_request(actor_id: int, payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="claims.coordination_claim.release",
        actor=ActorContext(actor_id=str(actor_id), session_id="holder-session"),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def test_release_by_claim_id_alone_resolves_the_claim_project(conn: Any):
    yoke = resolve_project_id(conn, "yoke")
    actor_id = _project_owner(conn, yoke)
    _session(conn, "holder-session", yoke)
    claim_id = _migration_claim(conn, project="yoke", session_id="holder-session")
    entry = _entry("claims.coordination_claim.release")

    request = _release_request(actor_id, {"claim_id": claim_id, "reason": "done"})

    assert resolve_project_context(conn, entry, request) == (yoke, "yoke")
    allowed = check_dispatch_permission(conn, entry, request)
    assert allowed.error is None
    assert allowed.project_id == yoke


def test_explicit_project_and_key_still_resolve(conn: Any):
    yoke = resolve_project_id(conn, "yoke")
    actor_id = _project_owner(conn, yoke)
    _session(conn, "holder-session", yoke)
    entry = _entry("claims.coordination_claim.release")

    request = _release_request(
        actor_id,
        {"project_id": "yoke", "key": "LIVE_DB_MIGRATION:core", "reason": "done"},
    )

    assert resolve_project_context(conn, entry, request) == (yoke, "yoke")
    assert check_dispatch_permission(conn, entry, request).error is None


def test_a_retired_deploy_key_refuses_naming_its_retirement():
    with pytest.raises(CoordinationKeyError, match="^deploy_lock_retired:") as refused:
        target_for_key("DEPLOY:yoke", project_id=1)
    assert "release --claim-id N" in str(refused.value)


def test_a_hold_from_before_the_retirement_still_renders_its_key():
    """Its holder lists it by key and releases it by id."""
    hold = WorkClaimTarget(
        TARGET_KIND_DEPLOY_SERIALIZATION, {"project_id": 1, "project_slug": "yoke"}
    )
    assert key_for_target(hold) == "DEPLOY:yoke"


def test_an_actor_without_the_claim_project_is_still_refused(conn: Any):
    """Resolving the target must not hand authority to a different tenant."""
    yoke = resolve_project_id(conn, "yoke")
    external = resolve_project_id(conn, "externalwebapp")
    _project_owner(conn, yoke)
    outsider = _project_owner(conn, external)
    _session(conn, "holder-session", yoke)
    claim_id = _migration_claim(conn, project="yoke", session_id="holder-session")
    entry = _entry("claims.coordination_claim.release")

    request = _release_request(outsider, {"claim_id": claim_id, "reason": "done"})

    assert resolve_project_context(conn, entry, request) == (yoke, "yoke")
    assert check_dispatch_permission(conn, entry, request).error is not None


def test_a_claim_id_naming_no_row_resolves_nothing(conn: Any):
    yoke = resolve_project_id(conn, "yoke")
    actor_id = _project_owner(conn, yoke)
    entry = _entry("claims.coordination_claim.release")

    request = _release_request(actor_id, {"claim_id": 987654, "reason": "done"})

    assert resolve_project_context(conn, entry, request) is None
    assert check_dispatch_permission(conn, entry, request).error is not None


def test_listing_by_session_alone_resolves_that_session_project(conn: Any):
    yoke = resolve_project_id(conn, "yoke")
    actor_id = _project_owner(conn, yoke)
    _session(conn, "holder-session", yoke)
    entry = _entry("claims.coordination_claim.list")

    request = FunctionCallRequest(
        function="claims.coordination_claim.list",
        actor=ActorContext(actor_id=str(actor_id), session_id="holder-session"),
        target=TargetRef(kind="global"),
        payload={"session_id": "holder-session"},
    )

    assert resolve_project_context(conn, entry, request) == (yoke, "yoke")


def test_qa_admission_release_by_claim_id_resolves_holding_session_project(
    conn: Any,
):
    yoke = resolve_project_id(conn, "yoke")
    actor_id = _project_owner(conn, yoke)
    _session(conn, "holder-session", yoke)
    claim_id = _qa_host_claim(conn, test_machine="mac-mini-lab", session_id="holder-session")
    entry = _entry("claims.coordination_claim.release")

    request = _release_request(actor_id, {"claim_id": claim_id, "reason": "done"})

    assert resolve_project_context(conn, entry, request) == (yoke, "yoke")
    allowed = check_dispatch_permission(conn, entry, request)
    assert allowed.error is None
    assert allowed.project_id == yoke


def test_qa_admission_release_refuses_an_actor_without_the_session_project(
    conn: Any,
):
    yoke = resolve_project_id(conn, "yoke")
    external = resolve_project_id(conn, "externalwebapp")
    outsider = _project_owner(conn, external)
    _session(conn, "holder-session", yoke)
    claim_id = _qa_host_claim(conn, test_machine="mac-mini-lab", session_id="holder-session")
    entry = _entry("claims.coordination_claim.release")

    request = _release_request(outsider, {"claim_id": claim_id, "reason": "done"})

    assert resolve_project_context(conn, entry, request) == (yoke, "yoke")
    assert check_dispatch_permission(conn, entry, request).error is not None


@pytest.mark.parametrize("function", ("list", "operator_release"))
@pytest.mark.parametrize("project_hint", (None, "externalwebapp"))
@pytest.mark.parametrize("authorized", (True, False))
def test_machine_recovery_and_list_retain_holder_project_authority(
    conn, function, project_hint, authorized
):
    yoke = resolve_project_id(conn, "yoke")
    external = resolve_project_id(conn, "externalwebapp")
    actor_id = _project_owner(conn, yoke if authorized else external)
    _session(conn, "holder-session", yoke)
    claim_id = _qa_host_claim(conn, test_machine="test-mac", session_id="holder-session")
    function_id = f"claims.coordination_claim.{function}"
    payload = {"key": "QA_HOST:test-mac", "active_only": True}
    if function == "operator_release":
        payload.update(
            claim_id=claim_id, holder_session_id="holder-session", reason="reviewed"
        )
    if project_hint is not None:
        payload["project_id"] = project_hint
    request = FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id=str(actor_id), session_id=""),
        target=TargetRef(kind="global"),
        payload=payload,
    )
    permission = check_dispatch_permission(conn, _entry(function_id), request)
    assert permission.project_id == yoke
    assert (permission.error is None) is authorized
