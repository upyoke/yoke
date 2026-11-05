"""Target-row project resolution for path claims and ouroboros entries."""

from __future__ import annotations

from runtime.api.domain.function_target_row_project_test_support import (_project_owner as _project_owner, _seed_item as _seed_item, _seed_path_claim as _seed_path_claim)
from runtime.api.domain.coordination_claim_project_authority_test_support import (conn as conn)


import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.function_target_resolution import resolve_project_context
from yoke_core.domain.function_target_row_project import (
    resolve_ouroboros_entry_project,
    resolve_path_claim_project,
)
from yoke_core.domain.ouroboros_entries import cmd_insert_entry
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.yoke_function_permissions import check_dispatch_permission
from yoke_core.domain.yoke_function_registry import RegistryEntry

from pydantic import BaseModel


class EmptyModel(BaseModel):
    pass


def _entry(function_id: str, *, side_effects: bool = False) -> RegistryEntry:
    return RegistryEntry(
        function_id=function_id,
        handler=lambda _request: None,
        request_model=EmptyModel,
        response_model=EmptyModel,
        stability="stable",
        owner_module=__name__,
        target_kinds=("path_claim", "global"),
        side_effects=("db_write",) if side_effects else (),
        emitted_event_names=(),
        guardrails=(),
        adapter_status="live",
    )


def test_resolve_path_claim_project_from_owning_item(conn):
    yoke = resolve_project_id(conn, "yoke")
    _seed_item(conn, item_id=42, project_id=yoke)
    _seed_path_claim(conn, claim_id=1048, item_id=42)
    assert resolve_path_claim_project(conn, 1048) == (yoke, "yoke")


def test_resolve_ouroboros_entry_project_from_note_row(conn):
    yoke = resolve_project_id(conn, "yoke")
    entry_id = int(
        cmd_insert_entry(
            conn,
            timestamp="2026-08-10T18:03:05Z",
            agent="test",
            
            category="observation",
            body="note body",
            project="yoke",
        yoke_version="0.2.0.202610290013", universe_fingerprint="fixture@2026-01-01T00:00:00Z")
    )
    assert resolve_ouroboros_entry_project(conn, entry_id) == (yoke, "yoke")


def test_claims_path_override_resolves_project_from_payload_claim_id(conn):
    yoke = resolve_project_id(conn, "yoke")
    _seed_item(conn, item_id=42, project_id=yoke)
    _seed_path_claim(conn, claim_id=1048, item_id=42)
    entry = _entry("claims.path.override", side_effects=True)
    request = FunctionCallRequest(
        function="claims.path.override",
        actor=ActorContext(actor_id="1", session_id="s-1"),
        target=TargetRef(kind="global"),
        payload={"path_claim_id": 1048},
    )
    assert resolve_project_context(conn, entry, request) == (yoke, "yoke")


def test_claims_path_get_authorizes_from_path_claim_row(conn):
    yoke = resolve_project_id(conn, "yoke")
    actor_id = _project_owner(conn, yoke)
    _seed_item(conn, item_id=42, project_id=yoke)
    _seed_path_claim(conn, claim_id=1048, item_id=42)
    entry = _entry("claims.path.get")
    request = FunctionCallRequest(
        function="claims.path.get",
        actor=ActorContext(actor_id=str(actor_id), session_id="s-1"),
        target=TargetRef(kind="path_claim", path_claim_id=1048),
        payload={},
    )
    allowed = check_dispatch_permission(conn, entry, request)
    assert allowed.error is None
    assert allowed.project_id == yoke
    assert resolve_project_context(conn, entry, request) == (yoke, "yoke")


def test_field_note_promote_authorizes_from_note_project_without_flag(conn):
    yoke = resolve_project_id(conn, "yoke")
    actor_id = _project_owner(conn, yoke)
    entry_id = int(
        cmd_insert_entry(
            conn,
            timestamp="2026-08-10T18:03:05Z",
            agent="test",
            
            category="observation",
            body="promote me",
            project="yoke",
        yoke_version="0.2.0.202610290013", universe_fingerprint="fixture@2026-01-01T00:00:00Z")
    )
    entry = _entry("ouroboros.field_note.promote", side_effects=True)
    request = FunctionCallRequest(
        function="ouroboros.field_note.promote",
        actor=ActorContext(actor_id=str(actor_id), session_id="s-1"),
        target=TargetRef(kind="global"),
        payload={"entry_id": entry_id, "title": "Promote without --project"},
    )
    allowed = check_dispatch_permission(conn, entry, request)
    assert allowed.error is None
    assert allowed.project_id == yoke


def test_explicit_project_still_overrides_note_row(conn):
    external = resolve_project_id(conn, "externalwebapp")
    actor_id = _project_owner(conn, external)
    entry_id = int(
        cmd_insert_entry(
            conn,
            timestamp="2026-08-10T18:04:05Z",
            agent="test",
            
            category="observation",
            body="note on yoke",
            project="yoke",
        yoke_version="0.2.0.202610290013", universe_fingerprint="fixture@2026-01-01T00:00:00Z")
    )
    entry = _entry("ouroboros.field_note.promote", side_effects=True)
    request = FunctionCallRequest(
        function="ouroboros.field_note.promote",
        actor=ActorContext(actor_id=str(actor_id), session_id="s-1"),
        target=TargetRef(kind="global"),
        payload={
            "entry_id": entry_id,
            "title": "Override project",
            "project": "externalwebapp",
        },
    )
    allowed = check_dispatch_permission(conn, entry, request)
    assert allowed.error is None
    assert allowed.project_id == external


def test_mark_archived_authorizes_from_entry_row_without_flag(conn):
    yoke = resolve_project_id(conn, "yoke")
    actor_id = _project_owner(conn, yoke)
    entry_id = int(
        cmd_insert_entry(
            conn,
            timestamp="2026-08-12T13:00:00Z",
            agent="test",
            
            category="failed",
            body="archive me by row project",
            project="yoke",
        yoke_version="0.2.0.202610290013", universe_fingerprint="fixture@2026-01-01T00:00:00Z")
    )
    entry = _entry("ouroboros.entry.mark_archived", side_effects=True)
    request = FunctionCallRequest(
        function="ouroboros.entry.mark_archived",
        actor=ActorContext(actor_id=str(actor_id), session_id="s-1"),
        target=TargetRef(kind="global"),
        payload={"entry_id": entry_id},
    )
    allowed = check_dispatch_permission(conn, entry, request)
    assert allowed.error is None
    assert allowed.project_id == yoke


def test_mark_archived_all_reviewed_authorizes_from_explicit_project(conn):
    yoke = resolve_project_id(conn, "yoke")
    actor_id = _project_owner(conn, yoke)
    entry = _entry("ouroboros.entry.mark_archived", side_effects=True)
    request = FunctionCallRequest(
        function="ouroboros.entry.mark_archived",
        actor=ActorContext(actor_id=str(actor_id), session_id="s-1"),
        target=TargetRef(kind="global"),
        payload={"all_reviewed": True, "project": "yoke"},
    )
    allowed = check_dispatch_permission(conn, entry, request)
    assert allowed.error is None
    assert allowed.project_id == yoke


def test_mark_archived_all_reviewed_without_project_is_denied(conn):
    yoke = resolve_project_id(conn, "yoke")
    actor_id = _project_owner(conn, yoke)
    entry = _entry("ouroboros.entry.mark_archived", side_effects=True)
    request = FunctionCallRequest(
        function="ouroboros.entry.mark_archived",
        actor=ActorContext(actor_id=str(actor_id), session_id="s-1"),
        target=TargetRef(kind="global"),
        payload={"all_reviewed": True},
    )
    denied = check_dispatch_permission(conn, entry, request)
    assert denied.error is not None
    assert "project_required: no project given" in (
        denied.error.error.message if denied.error.error else ""
    )


@pytest.mark.parametrize("owner_slug", ["yoke", "externalwebapp"])
@pytest.mark.parametrize("item_id", [42, None])
@pytest.mark.parametrize("project_hint", [None, "externalwebapp"])
def test_ci_rerun_authority_comes_from_its_item(
    conn, owner_slug, item_id, project_hint
):
    project_id = resolve_project_id(conn, "yoke")
    actor_id = _project_owner(conn, resolve_project_id(conn, owner_slug))
    _seed_item(conn, item_id=42, project_id=project_id)
    function = "github_actions.run.rerun_failed"
    payload = {"run_id": "100"}
    if project_hint is not None:
        payload["project"] = project_hint
    request = FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id=str(actor_id), session_id="worker"),
        target=TargetRef(kind="item", item_id=item_id),
        payload=payload,
    )
    allowed = check_dispatch_permission(
        conn, _entry(function, side_effects=True), request
    )
    assert allowed.project_id == (project_id if item_id is not None else None)
    assert (allowed.error is None) == (item_id is not None and owner_slug == "yoke")
