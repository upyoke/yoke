"""Who may spend a machine's capacity, per its registered access document."""

from __future__ import annotations

from yoke_contracts.machine_config import machine_access
from yoke_core.domain import machine_registry
from yoke_core.domain.machine_access_authority import actor_may_use_machine
from runtime.api.domain.machine_registry_test_support import (
    MACHINE_ID,
    NOW,
    grant_project_role,
    registry_connection,
)


def _register(conn, *, access=None, actor_id: int = 1):
    machine_registry.register_machine(
        conn,
        machine_id=MACHINE_ID,
        name="workshop-mac",
        actor_id=actor_id,
        access=access,
        now=NOW,
    )


def _decide(conn, actor_id: int, **kwargs):
    return actor_may_use_machine(
        conn, machine_id=MACHINE_ID, actor_id=actor_id, project_id=10, **kwargs
    )


def test_an_unregistered_machine_admits_nobody():
    conn = registry_connection()
    decision = _decide(conn, 1)
    assert decision.allowed is False
    assert "yoke machine register" in decision.reason


def test_owner_only_admits_the_owner_and_refuses_everyone_else():
    conn = registry_connection()
    _register(conn)
    assert _decide(conn, 1).allowed is True
    denied = _decide(conn, 2)
    assert denied.allowed is False
    assert denied.setting == machine_access.USE_SETTING
    assert machine_access.USE_OWNER_ONLY in denied.reason


def test_an_administrator_may_use_a_machine_they_do_not_own():
    conn = registry_connection()
    _register(conn)
    assert _decide(conn, 2, is_admin=True).allowed is True


def test_a_named_actor_list_admits_exactly_those_actors():
    conn = registry_connection()
    _register(
        conn,
        access={"use": {"mode": machine_access.USE_ACTORS, "actor_ids": [2]}},
    )
    assert _decide(conn, 2).allowed is True
    assert _decide(conn, 3).allowed is False


def test_a_project_role_admits_holders_of_that_role():
    conn = registry_connection()
    _register(
        conn,
        access={
            "use": {
                "mode": machine_access.USE_PROJECT_ROLE,
                "project_id": 10,
                "role": "maintainer",
            }
        },
    )
    assert _decide(conn, 2).allowed is False
    grant_project_role(conn, actor_id=2)
    assert _decide(conn, 2).allowed is True


def test_universe_mode_admits_every_member():
    conn = registry_connection()
    _register(conn, access={"use": {"mode": machine_access.USE_UNIVERSE}})
    assert _decide(conn, 3).allowed is True


def test_an_unrecognized_mode_admits_nobody_and_says_why():
    conn = registry_connection()
    conn.execute(
        "INSERT INTO machines (machine_id,name,owner_actor_id,"
        "access,registered_at,last_seen_at) VALUES (?,?,?,?,?,?)",
        (MACHINE_ID, "n", 1, '{"use": {"mode": "nonsense"}}', NOW, NOW),
    )
    conn.commit()
    decision = _decide(conn, 2)
    assert decision.allowed is False
    assert "not a recognized mode" in decision.reason


def test_offer_lists_narrow_only_when_populated():
    document = {"offers": {"executor_surfaces": ["claude-cli"], "models": []}}
    assert machine_access.offers_surface(document, "claude-cli") is True
    assert machine_access.offers_surface(document, "codex-cli") is False
    assert machine_access.offers_model(document, "anything") is True
