"""A session's steering seats list across every project the caller can read."""

from __future__ import annotations

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.claims_steering import handle_list
from yoke_core.domain.steering_claims import list_claims
from yoke_core.domain.yoke_function_permissions import check_dispatch_permission
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.yoke_function_registry import lookup
from runtime.api.domain.steering_claim_test_support import (
    HUMAN_ACTOR_ID,
    PROJECT_ALPHA,
    PROJECT_BETA,
    SESSION_ALPHA,
    acquire_steering,
    seed_standard_steering_world,
)


@pytest.fixture
def two_project_seats(test_db):
    seed_standard_steering_world(test_db)
    acquire_steering(test_db, SESSION_ALPHA, PROJECT_ALPHA)
    acquire_steering(test_db, SESSION_ALPHA, PROJECT_BETA)
    return test_db


def _request(payload, *, project=None, visible=None) -> FunctionCallRequest:
    options = {}
    if project is not None:
        options["authorized_project_id"] = project
    if visible is not None:
        options["visible_project_ids"] = visible
    return FunctionCallRequest(
        function="claims.steering.list",
        actor=ActorContext(actor_id=str(HUMAN_ACTOR_ID), session_id=SESSION_ALPHA),
        target=TargetRef(kind="global", project_id=project and str(project)),
        payload=payload,
        options=options,
    )


def _projects(claims) -> list[int]:
    return sorted(int(claim["scope"]["project_id"]) for claim in claims)


def test_session_filter_without_project_lists_every_project(two_project_seats):
    rows = list_claims(two_project_seats, session_id=SESSION_ALPHA, active_only=True)
    assert _projects(rows) == [PROJECT_ALPHA, PROJECT_BETA]

    one = list_claims(two_project_seats, project_id=PROJECT_BETA, session_id=SESSION_ALPHA)
    assert _projects(one) == [PROJECT_BETA]


def test_handler_lists_only_seats_in_projects_the_caller_reads(two_project_seats):
    both = handle_list(
        _request(
            {"session_id": SESSION_ALPHA}, visible=[PROJECT_ALPHA, PROJECT_BETA]
        )
    )
    assert _projects(both.result_payload["claims"]) == [PROJECT_ALPHA, PROJECT_BETA]

    narrowed = handle_list(_request({"session_id": SESSION_ALPHA}, visible=[PROJECT_BETA]))
    assert _projects(narrowed.result_payload["claims"]) == [PROJECT_BETA]

    scoped = handle_list(_request({"session_id": SESSION_ALPHA}, project=PROJECT_ALPHA))
    assert _projects(scoped.result_payload["claims"]) == [PROJECT_ALPHA]


def test_handler_without_project_or_session_names_both_scopes(two_project_seats):
    outcome = handle_list(_request({}))
    assert outcome.error.code == "project_context_required"
    assert "--project P" in outcome.error.message
    assert "--session-id S" in outcome.error.message


def test_permission_hands_the_session_list_the_readable_projects(two_project_seats):
    two_project_seats.execute(
        "INSERT INTO actor_project_roles (actor_id, project_id, role_id, granted_at) "
        "SELECT %s, %s, id, NOW() FROM roles WHERE name = 'viewer'",
        (HUMAN_ACTOR_ID, PROJECT_ALPHA),
    )
    two_project_seats.commit()
    register_all_handlers()
    permission = check_dispatch_permission(
        two_project_seats,
        lookup("claims.steering.list"),
        _request({"session_id": SESSION_ALPHA}),
    )
    assert permission.error is None
    assert permission.project_id is None
    assert PROJECT_ALPHA in permission.visible_project_ids
    assert PROJECT_BETA not in permission.visible_project_ids
