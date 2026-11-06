"""Missing selection teaches only the caller's permitted project roster."""

from runtime.api.fixtures.actor_roles import seed_project_role

import pytest

from runtime.api.domain.function_permission_test_support import _conn, _entry
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.actor_permissions import (
    ROLE_OWNER,
)
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.yoke_function_permissions import check_dispatch_permission


@pytest.mark.parametrize(
    "function",
    [
        "items.create",
        "packs.list",
        "github_actions.secret.set",
        "doctor.run.run",
        "qa.plan.create",
    ],
)
def test_missing_selection_names_only_accessible_project(function):
    with _conn() as conn:
        actor_id = seed_human_actor(conn)
        allowed = resolve_project_id(conn, "externalwebapp")
        seed_project_role(
            conn,
            actor_id=actor_id,
            project_id=allowed,
            role_name=ROLE_OWNER,
            granted_by_actor_id=actor_id,
        )
        entry = _entry(function)
        request = FunctionCallRequest(
            function=function,
            actor=ActorContext(actor_id=str(actor_id), session_id="test"),
            target=TargetRef(kind="global"),
            payload=(
                {"quick": True, "project_safe_quick": True}
                if function == "doctor.run.run"
                else {"slug": "a-plan-name"}
                if function == "qa.plan.create"
                else {}
            ),
        )
        refusal = check_dispatch_permission(conn, entry, request).error.error
        assert refusal.code == "project_required"
        assert refusal.message.endswith("Accessible projects: externalwebapp.")
        assert "yoke" not in refusal.message


@pytest.mark.parametrize("project", ["unregistered", "yoke"])
def test_supplied_project_keeps_permission_refusal(project):
    with _conn() as conn:
        actor_id = seed_human_actor(conn)
        entry = _entry("items.structured_field.replace")
        request = FunctionCallRequest(
            function=entry.function_id,
            actor=ActorContext(actor_id=str(actor_id), session_id="test"),
            target=TargetRef(kind="global", project_id=project),
            payload={},
        )
        refusal = check_dispatch_permission(conn, entry, request).error.error
        assert refusal.code == "permission_denied"
        assert "Accessible projects" not in refusal.message


def test_unresolved_item_does_not_become_missing_selection():
    with _conn() as conn:
        actor_id = seed_human_actor(conn)
        entry = _entry("items.structured_field.replace")
        request = FunctionCallRequest(
            function=entry.function_id,
            actor=ActorContext(actor_id=str(actor_id), session_id="test"),
            target=TargetRef(kind="item", item_id=999999),
            payload={},
        )
        assert (
            check_dispatch_permission(conn, entry, request).error.error.code
            == "permission_denied"
        )


@pytest.mark.parametrize("reason", ["ambiguous_project", "permission_denied"])
def test_resolver_refusals_keep_their_causes(monkeypatch, reason):
    from yoke_core.domain import yoke_function_permissions
    from yoke_core.domain.function_unresolved_project import ProjectNotRegisteredError
    from yoke_core.domain.project_identity import AmbiguousProjectRefError

    def refuse(*_args, **_kwargs):
        if reason == "ambiguous_project":
            raise AmbiguousProjectRefError(
                "project name is ambiguous; name its organization"
            )
        raise ProjectNotRegisteredError("missing", plane="test")

    monkeypatch.setattr(yoke_function_permissions, "resolve_project_context", refuse)
    with _conn() as conn:
        actor_id = seed_human_actor(conn)
        entry = _entry("github_actions.secret.set")
        request = FunctionCallRequest(
            function=entry.function_id,
            actor=ActorContext(actor_id=str(actor_id), session_id="test"),
            target=TargetRef(kind="global"),
            payload={"project": "supplied"},
        )
        refusal = check_dispatch_permission(conn, entry, request).error.error
        assert refusal.code == reason
        assert "Accessible projects" not in refusal.message


@pytest.mark.parametrize("run_id", [999999, 0, -1])
def test_unknown_capture_does_not_disclose_an_unresolved_subject(run_id):
    with _conn() as conn:
        actor_id = seed_human_actor(conn)
        seed_project_role(
            conn,
            actor_id=actor_id,
            project_id=resolve_project_id(conn, "externalwebapp"),
            role_name=ROLE_OWNER,
            granted_by_actor_id=actor_id,
        )
        entry = _entry("qa.run.get")
        request = FunctionCallRequest(
            function=entry.function_id,
            actor=ActorContext(actor_id=str(actor_id), session_id="hosted-member"),
            target=TargetRef(kind="global"),
            payload={"run_id": run_id},
        )
        response = check_dispatch_permission(conn, entry, request).error
        assert response.success is False
        assert response.error.code == "permission_denied"
        assert response.result == {}
        assert "Accessible projects" not in response.error.message


@pytest.mark.parametrize("key", ["requirement_id", "plan_id", "execution_id", "id"])
def test_supplied_record_identity_is_not_missing_project_selection(key):
    from yoke_core.domain.function_project_selection import project_selection_missing

    request = FunctionCallRequest(
        function="qa.run.get",
        actor=ActorContext(actor_id="1", session_id="test"),
        target=TargetRef(kind="global"),
        payload={key: "missing"},
    )
    assert not project_selection_missing(request)
