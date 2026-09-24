"""The browser roster reads actor identity and grants without mutating them."""

from __future__ import annotations

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.actors import seed_human_actor, seed_system_actor
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.handlers.actors_roster import handle_actors_roster
from yoke_core.domain.profile_read import read_roles
from yoke_core.ui.function_proxy import (
    UI_ACTOR_BOUND_READ_FUNCTIONS,
    UI_READ_FUNCTION_ALLOWLIST,
)


def _request(actor_id, target=None):
    return FunctionCallRequest(
        function="actors.roster",
        actor=ActorContext(actor_id=str(actor_id), session_id=""),
        target=target or TargetRef(kind="global"),
        payload={},
    )


def test_roster_reads_every_actor_with_roles_and_linked_identity(test_db):
    human = seed_human_actor(test_db, "Dana")
    system = seed_system_actor(test_db, "deploy-ci")
    test_db.execute(
        "INSERT INTO actor_external_identities "
        "(actor_id, issuer, subject, email, linked_at) "
        "VALUES (%s, 'https://accounts.google.com', 'dana', 'dana@example.test', %s)",
        (human, iso8601_now()),
    )
    test_db.commit()

    result = handle_actors_roster(_request(human))
    assert result.primary_success, result.error
    payload = result.result_payload
    assert payload["current_actor_id"] == human
    rows = payload["rows"]
    assert [row["id"] for row in rows] == sorted(row["id"] for row in rows)
    dana = next(row for row in rows if row["id"] == human)
    assert dana["name"] == "Dana"
    assert dana["kind"] == "human"
    assert dana["roles"] == read_roles(test_db, human)
    assert dana["identity"]["email"] == "dana@example.test"
    deploy = next(row for row in rows if row["id"] == system)
    assert deploy["name"] == "deploy-ci"
    assert deploy["kind"] == "system"
    assert deploy["identity"] is None


def test_roster_requires_a_global_target(test_db):
    result = handle_actors_roster(
        _request(
            1,
            TargetRef(kind="item", item_id=1),
        )
    )
    assert result.primary_success is False
    assert result.error.code == "target_invalid"
    assert "retry" in result.error.message


def test_local_browser_proxy_admits_the_actor_bound_roster():
    assert "actors.roster" in UI_READ_FUNCTION_ALLOWLIST
    assert "actors.roster" in UI_ACTOR_BOUND_READ_FUNCTIONS
