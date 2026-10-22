"""Item targets own project authority across registered function families."""

from contextlib import nullcontext

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    HandlerOutcome,
    TargetRef,
)
from yoke_core.domain import yoke_function_dispatch as dispatcher
from yoke_core.domain.function_authz_scope import PROJECT, classify, permission_key_for
from yoke_core.domain.function_target_resolution import resolve_project_context
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.yoke_function_actor_identity import BoundIdentity
from yoke_core.domain.yoke_function_permissions import check_dispatch_permission
from yoke_core.domain.yoke_function_registry import (
    list_entries,
    lookup,
    reset_registry_for_tests,
)
from runtime.api.domain.test_function_target_row_project import (
    conn as project_connection,
    _project_owner,
    _seed_item,
    _seed_path_claim,
)

conn = project_connection


@pytest.fixture
def item_dispatch(conn, monkeypatch):
    reset_registry_for_tests()
    register_all_handlers()
    project_id = resolve_project_id(conn, "externalwebapp")
    actor_id = _project_owner(conn, project_id)
    _seed_item(conn, item_id=42, project_id=project_id)
    _seed_path_claim(conn, claim_id=1048, item_id=42)
    seen = []
    monkeypatch.setattr(dispatcher, "_ensure_handlers_registered", lambda: None)
    monkeypatch.setattr(
        dispatcher,
        "bind_actor_identity",
        lambda entry, request, **kwargs: BoundIdentity(request, "worker", "worker"),
    )
    monkeypatch.setattr(dispatcher, "resolve_request_item_refs", lambda *args: None)
    monkeypatch.setattr(
        dispatcher,
        "dispatch_permission_for_request",
        lambda entry, request: check_dispatch_permission(conn, entry, request),
    )
    monkeypatch.setattr(dispatcher, "handle_idempotency", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        dispatcher.idempotency_module,
        "request_reservation",
        lambda *args: nullcontext(),
    )
    monkeypatch.setattr(dispatcher, "verify_claim", lambda *args, **kwargs: None)
    monkeypatch.setattr(dispatcher, "emit_called", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        dispatcher, "emit_permission_denied", lambda *args, **kwargs: None
    )

    def handler(_handler, request):
        seen.append(request)
        return HandlerOutcome(
            result_payload={
                "authorized_project": request.options.get("authorized_project_id")
            }
        )

    monkeypatch.setattr(dispatcher, "invoke_handler", handler)
    yield conn, actor_id, project_id, seen
    reset_registry_for_tests()


def _request(function_id, actor_id, *, payload=None, item_id=42):
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id=str(actor_id), session_id="worker"),
        target=TargetRef(kind="item", item_id=item_id),
        payload=payload or {},
    )


def test_rerun_failed_reaches_handler_through_project_permission(item_dispatch):
    _, actor_id, project_id, seen = item_dispatch
    response = dispatcher.dispatch(
        _request("github_actions.run.rerun_failed", actor_id, payload={"run_id": "100"})
    )
    assert response.success, response.error
    assert response.result["authorized_project"] == project_id
    assert seen[0].payload == {"run_id": "100"}


def test_every_registered_item_target_resolves_its_stored_project(item_dispatch):
    connection, actor_id, project_id, seen = item_dispatch
    entries = [entry for entry in list_entries() if "item" in entry.target_kinds]
    assert entries
    assert any(
        entry.function_id == "github_actions.run.rerun_failed" for entry in entries
    )
    for entry in entries:
        request = _request(entry.function_id, actor_id, payload={"project": "yoke"})
        from yoke_core.domain.qa_execution_request_identity import is_execution_request
        from yoke_core.domain.qa_deployment_function_subject import (
            QaSubjectProjectError,
        )

        if is_execution_request(request):
            with pytest.raises(QaSubjectProjectError, match="qa_execution_id_required"):
                resolve_project_context(connection, entry, request)
            continue
        if entry.function_id == "claims.path.override":
            request.payload["path_claim_id"] = 1048
        assert resolve_project_context(connection, entry, request) == (
            project_id,
            "externalwebapp",
        ), entry.function_id
        scope = classify(
            entry.function_id,
            side_effects=bool(entry.side_effects),
            project_permission=permission_key_for(entry),
        )
        if scope.scope == PROJECT:
            response = dispatcher.dispatch(request)
            assert response.success, (entry.function_id, response.error)
            assert seen[-1].options["authorized_project_id"] == project_id


def test_missing_item_cannot_authorize_using_project_hint(item_dispatch):
    connection, actor_id, _, seen = item_dispatch
    request = _request(
        "github_actions.run.rerun_failed",
        actor_id,
        payload={"run_id": "100", "project": "externalwebapp"},
        item_id=999,
    )
    assert (
        resolve_project_context(connection, lookup(request.function), request) is None
    )
    response = dispatcher.dispatch(request)
    assert not response.success
    assert response.error.code == "permission_denied"
    assert not seen


def test_item_permission_uses_stored_project_instead_of_hints(item_dispatch):
    connection, actor_id, project_id, _ = item_dispatch
    request = _request(
        "items.structured_field.replace", actor_id, payload={"project": "yoke"}
    )
    entry = lookup(request.function)
    allowed = check_dispatch_permission(connection, entry, request)
    assert allowed.error is None
    assert allowed.permission_key == "items.write"
    assert allowed.project_id == project_id
    other_project = resolve_project_id(connection, "yoke")
    _seed_item(connection, item_id=43, project_id=other_project)
    request.target.item_id = 43
    request.payload["project"] = "externalwebapp"
    denied = check_dispatch_permission(connection, entry, request)
    assert denied.error.error.code == "permission_denied"
    assert denied.project_id == other_project
