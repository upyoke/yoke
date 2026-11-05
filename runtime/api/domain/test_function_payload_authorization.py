"""Authorization of project payloads and actor-scoped dispatch."""

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.yoke_function_permissions import check_dispatch_permission
from runtime.api.domain.function_authz_scope_routing_test_support import (
    conn as conn,
    _new_actor,
    _project_owner,
    _org_admin,
    _org_of,
    _entry,
    _payload_request,
    _request,
    _no_actor_request,
)


def test_board_data_get_resolves_project_from_payload_scope(conn):
    # board.data.get names its project in payload.scope; it must resolve + be
    # checked against that project (not bypassed), so cross-project board reads
    # are denied.
    externalwebapp = resolve_project_id(conn, "externalwebapp")
    externalwebapp_owner = _project_owner(conn, externalwebapp)
    entry = _entry("board.data.get", side_effects=False)
    allowed = check_dispatch_permission(
        conn,
        entry,
        _payload_request(
            externalwebapp_owner, "board.data.get", {"scope": "externalwebapp"}
        ),
    )
    assert allowed.error is None
    assert allowed.project_slug == "externalwebapp"
    denied = check_dispatch_permission(
        conn,
        entry,
        _payload_request(externalwebapp_owner, "board.data.get", {"scope": "yoke"}),
    )
    assert denied.error is not None


def test_payload_named_project_target_hint_must_match_payload(conn):
    externalwebapp = resolve_project_id(conn, "externalwebapp")
    externalwebapp_owner = _project_owner(conn, externalwebapp)
    entry = _entry("projects.update")

    denied = check_dispatch_permission(
        conn,
        entry,
        FunctionCallRequest(
            function="projects.update",
            actor=ActorContext(actor_id=str(externalwebapp_owner), session_id="s-1"),
            target=TargetRef(kind="global", project_id="yoke"),
            payload={"slug": "externalwebapp", "name": "ExternalWebapp"},
        ),
    )

    assert denied.error is not None
    assert denied.error.error.code == "permission_denied"


def test_unclassified_side_effecting_function_fails_closed(conn):
    actor_id = _new_actor(conn)
    entry = _entry("totally.unknown.sideeffecting.op")
    res = check_dispatch_permission(
        conn,
        entry,
        _request(actor_id, "totally.unknown.sideeffecting.op", project="yoke"),
    )
    assert res.error is not None
    assert "denied by default" in res.error.error.message


def test_client_local_op_allowed_without_actor(conn):
    entry = _entry("auth.set.run")
    res = check_dispatch_permission(conn, entry, _no_actor_request("auth.set.run"))
    assert res.error is None
    assert res.permission_key is None


def test_actor_session_op_allowed_with_actor(conn):
    actor_id = _new_actor(conn)
    entry = _entry("sessions.touch")
    assert (
        check_dispatch_permission(
            conn, entry, _request(actor_id, "sessions.touch")
        ).error
        is None
    )


def test_side_effecting_call_without_verified_actor_refuses_actor_required(conn):
    # No numeric actor -> nothing to authorize or attribute -> refused for
    # every side-effecting scope, including the unclassified DENY bucket.
    for function_id in (
        "items.structured_field.replace",
        "totally.unknown.sideeffecting.op",
    ):
        res = check_dispatch_permission(
            conn, _entry(function_id), _no_actor_request(function_id)
        )
        assert res.error is not None
        assert res.error.error.code == "actor_required"
        assert "yoke setup" in res.error.error.message


def test_projects_create_is_org_scoped_update_is_project_scoped(conn):
    yoke = resolve_project_id(conn, "yoke")
    externalwebapp = resolve_project_id(conn, "externalwebapp")
    org_admin = _org_admin(conn, _org_of(conn, yoke))
    externalwebapp_owner = _project_owner(conn, externalwebapp)

    # projects.create is org-scoped: an org admin may register; a project
    # owner (even of an existing project) may not.
    create = _entry("projects.create")
    create_payload = {"slug": "newproj", "name": "New"}
    assert (
        check_dispatch_permission(
            conn, create, _payload_request(org_admin, "projects.create", create_payload)
        ).error
        is None
    )
    assert (
        check_dispatch_permission(
            conn,
            create,
            _payload_request(externalwebapp_owner, "projects.create", create_payload),
        ).error
        is not None
    )

    # projects.update is project-scoped on the TARGET resolved from payload slug:
    # externalwebapp's owner may update externalwebapp, but not yoke.
    update = _entry("projects.update")
    res = check_dispatch_permission(
        conn,
        update,
        _payload_request(
            externalwebapp_owner,
            "projects.update",
            {"slug": "externalwebapp", "name": "ExternalWebapp"},
        ),
    )
    assert res.error is None
    assert res.project_slug == "externalwebapp"
    assert (
        check_dispatch_permission(
            conn,
            update,
            _payload_request(
                externalwebapp_owner,
                "projects.update",
                {"slug": "yoke", "name": "Yoke"},
            ),
        ).error
        is not None
    )
