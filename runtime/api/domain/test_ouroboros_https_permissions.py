"""Authorization coverage for HTTPS Ouroboros close-out."""

from __future__ import annotations

from runtime.api.domain.test_yoke_function_permissions import _entry
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.actor_permissions import (
    ROLE_OWNER,
    grant_actor_project_role,
    seed_roles_and_permissions,
)
from yoke_core.domain.function_authz_scope import PROJECT, classify
from yoke_core.domain.ouroboros_entries import cmd_insert_entry
from yoke_core.domain.ouroboros_entry_review import MAX_ENTRY_REVIEW_BATCH
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.yoke_function_permissions import (
    check_dispatch_permission,
    permission_key_for,
)


REVIEW = "ouroboros.entry.mark_reviewed"
ARCHIVE = "ouroboros.entry.mark_archived"


def _request(function_id: str, actor_id: int, payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id=str(actor_id), session_id="https-session"),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def _project_owner(conn, project_slug: str) -> int:
    seed_roles_and_permissions(conn)
    actor_id = int(
        conn.execute(
            "INSERT INTO actors (kind, created_at) "
            "VALUES ('human', '2026-01-01T00:00:00Z') RETURNING id"
        ).fetchone()[0]
    )
    grant_actor_project_role(
        conn,
        actor_id=actor_id,
        project_id=resolve_project_id(conn, project_slug),
        role_name=ROLE_OWNER,
        granted_by_actor_id=actor_id,
    )
    conn.commit()
    return actor_id


def _seed_entry(conn, body: str, project: str | None) -> int:
    entry_id = int(
        cmd_insert_entry(
            conn, "2026-07-01T00:00:00Z", "tester", None, "friction", body, project,
        )
    )
    conn.commit()
    return entry_id


def _denied_message(permission) -> str:
    return permission.error.error.message if permission.error else ""


def test_entry_close_out_is_project_scoped() -> None:
    """Review carries the same project scope its sibling archive does.

    An actor-session scope returns before any permission check, which would
    let any authenticated actor close out every project's learning queue.
    """
    for function_id in (REVIEW, ARCHIVE):
        entry = _entry(function_id)
        spec = classify(
            function_id,
            side_effects=bool(entry.side_effects),
            project_permission=permission_key_for(entry),
        )
        assert spec.scope == PROJECT
        assert spec.permission_key == permission_key_for(entry)


def test_review_by_id_authorizes_from_the_entry_row(test_db) -> None:
    actor_id = _project_owner(test_db, "yoke")
    entry_id = _seed_entry(test_db, "review by row authority", "yoke")

    permission = check_dispatch_permission(
        test_db, _entry(REVIEW), _request(REVIEW, actor_id, {"entry_id": entry_id}),
    )

    assert permission.error is None
    assert permission.project_id == resolve_project_id(test_db, "yoke")


def test_entry_close_out_refuses_a_caller_project_that_is_not_the_rows(
    test_db,
) -> None:
    actor_id = _project_owner(test_db, "externalwebapp")

    for function_id in (REVIEW, ARCHIVE):
        entry_id = _seed_entry(test_db, f"row owned elsewhere: {function_id}", "yoke")
        payload = {"entry_id": entry_id, "project": "externalwebapp"}

        permission = check_dispatch_permission(
            test_db, _entry(function_id), _request(function_id, actor_id, payload),
        )

        assert permission.error is not None
        assert "could not resolve a target project" in _denied_message(permission)


def test_cutoff_review_without_a_project_resolves_no_target(test_db) -> None:
    actor_id = _project_owner(test_db, "yoke")
    payload = {"before": "2026-08-01", "limit": MAX_ENTRY_REVIEW_BATCH}

    permission = check_dispatch_permission(
        test_db, _entry(REVIEW), _request(REVIEW, actor_id, payload),
    )

    assert permission.error is not None
    assert "could not resolve a target project" in _denied_message(permission)


def test_cutoff_review_authorizes_the_named_project(test_db) -> None:
    actor_id = _project_owner(test_db, "yoke")
    payload = {"before": "2026-08-01", "project": "yoke"}

    permission = check_dispatch_permission(
        test_db, _entry(REVIEW), _request(REVIEW, actor_id, payload),
    )

    assert permission.error is None
    assert permission.project_id == resolve_project_id(test_db, "yoke")


def test_cutoff_review_denies_a_project_the_actor_does_not_hold(test_db) -> None:
    actor_id = _project_owner(test_db, "externalwebapp")
    payload = {"before": "2026-08-01", "project": "yoke"}

    permission = check_dispatch_permission(
        test_db, _entry(REVIEW), _request(REVIEW, actor_id, payload),
    )

    assert permission.error is not None
