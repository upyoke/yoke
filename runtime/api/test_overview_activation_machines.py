"""The harness activation module answered per registered machine.

Drives ``overview.activation.get`` against a universe with more than one
machine: the wizard row counts and names them, the harness module carries
one row per machine with its own state and hook health, the module reads
next up while any machine has connected nothing, and every latch is
monotone per machine.
"""

from __future__ import annotations

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.handlers.overview_activation import (
    handle_overview_activation_get,
)

MACHINE_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
MACHINE_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def _modules(payload=None):
    outcome = handle_overview_activation_get(FunctionCallRequest(
        function="overview.activation.get",
        actor=ActorContext(actor_id=None, session_id=""),
        target=TargetRef(kind="global"),
        payload=payload or {},
    ))
    assert outcome.primary_success, outcome.error
    return {m["key"]: m for m in outcome.result_payload["modules"]}


def _seed_relay(conn, machine_id, hostname):
    actor = conn.execute("SELECT id FROM actors ORDER BY id LIMIT 1").fetchone()[0]
    now = iso8601_now()
    conn.execute(
        "INSERT INTO session_relays (relay_id, actor_id, machine_id, hostname, "
        "surface_versions, project_checkouts, first_seen_at, last_seen_at, "
        "connected_until, state) VALUES (%s, %s, %s, %s, "
        "'{\"claude-cli\": \"2.1\", \"codex-cli\": \"0.1\"}', '[]', %s, %s, %s, 'active')",
        (f"machine:{machine_id}", actor, machine_id, hostname, now, now, now),
    )
    conn.commit()


def _seed_session(conn, session_id, machine_id, *, executor="claude-code",
                  surface=None, tool_calls=0):
    now = iso8601_now()
    conn.execute(
        "INSERT INTO harness_sessions (session_id, executor, executor_surface, "
        "machine_id, provider, model, workspace, project_id, mode, offered_at, "
        "last_heartbeat, tool_call_count) "
        "VALUES (%s, %s, %s, %s, 'anthropic', 'm', '/w', 1, 'wait', %s, %s, %s)",
        (session_id, executor, surface, machine_id, now, now, tool_calls),
    )
    conn.commit()


def _machines(harness_module):
    return {row["machine_id"]: row for row in harness_module["machines"]}


def _health(machine):
    """Coloured targets only; an undetected surface carries no colour."""
    return {
        target["key"]: target["hook_health"]
        for target in machine["targets"] if target["hook_health"]
    }


def test_a_relay_only_machine_stays_next_up_beside_a_connected_one(test_db):
    _seed_relay(test_db, MACHINE_A, "alpha-box")
    _seed_relay(test_db, MACHINE_B, "beta-box")
    _seed_session(
        test_db, "s-a", MACHINE_A, surface="claude-cli", tool_calls=2,
    )

    modules = _modules()

    wizard = modules["finish_installation_wizard"]
    machine_row = wizard["submodules"][0]
    # Registered machines satisfy the row with no host fact at all.
    assert machine_row["done"] is True
    assert machine_row["detail"] is None
    assert [m["name"] for m in machine_row["machines"]] == ["alpha-box", "beta-box"]
    assert all(m["connected_at"] for m in machine_row["machines"])
    assert wizard["state"] == "activated"

    harness = modules["connect_harness"]
    assert harness["state"] == "in_progress"
    assert harness["activated_at"] is None
    rows = _machines(harness)
    alpha, beta = rows[MACHINE_A], rows[MACHINE_B]
    assert alpha["state"] == "activated" and alpha["activated_at"]
    assert alpha["connected"]["executor"] == "claude-code"
    assert alpha["surfaces"] == ["claude-cli", "codex-cli"]
    assert _health(alpha) == {
        "claude-code": "green",
        "claude-cli": "green",
        "codex": "orange",
        "codex-cli": "orange",
    }
    # The second box reads only its relay-reported installation, never the
    # first box's session history.
    assert beta["state"] == "in_progress" and beta["activated_at"] is None
    assert beta["connected"] is None
    assert _health(beta) == {
        "claude-code": "orange",
        "claude-cli": "orange",
        "codex": "orange",
        "codex-cli": "orange",
    }
    # Every other supported surface still answers, in words.
    assert {
        t["key"] for t in beta["targets"] if t["status"] == "not_installed"
    } == {"cursor", "cursor-cli", "cursor-desktop", "claude-vscode"}
    # Later modules stay locked behind the pending machine.
    assert modules["run_onboard"]["state"] == "not_started"


def test_every_machine_connected_activates_the_module(test_db):
    _seed_relay(test_db, MACHINE_A, "alpha-box")
    _seed_relay(test_db, MACHINE_B, "beta-box")
    _seed_session(test_db, "s-a", MACHINE_A)
    _seed_session(test_db, "s-b", MACHINE_B, executor="codex", surface="codex-cli")

    harness = _modules()["connect_harness"]

    assert harness["state"] == "activated"
    assert harness["activated_at"]
    assert all(row["state"] == "activated" for row in harness["machines"])


def test_the_harness_latch_holds_per_machine_when_sessions_vanish(test_db):
    _seed_relay(test_db, MACHINE_A, "alpha-box")
    _seed_session(test_db, "s-a", MACHINE_A)
    first = _modules()["connect_harness"]
    assert first["state"] == "activated"
    activated_at = _machines(first)[MACHINE_A]["activated_at"]

    test_db.execute("DELETE FROM harness_sessions")
    test_db.commit()
    again = _modules()["connect_harness"]
    assert again["state"] == "activated"
    assert _machines(again)[MACHINE_A]["activated_at"] == activated_at

    # A machine that registers afterwards starts with no latch of its own.
    _seed_relay(test_db, MACHINE_B, "beta-box")
    later = _modules()["connect_harness"]
    assert later["state"] == "in_progress"
    assert _machines(later)[MACHINE_A]["activated_at"] == activated_at
    assert _machines(later)[MACHINE_B]["activated_at"] is None


def test_a_universe_latch_row_for_the_harness_module_is_inert(test_db):
    test_db.execute(
        "INSERT INTO overview_activation_facts (module_key, activated_at) "
        "VALUES ('connect_harness', %s)",
        (iso8601_now(),),
    )
    test_db.commit()

    harness = _modules(payload={"host_facts": {"machine_connected": True}})["connect_harness"]

    assert harness["state"] == "in_progress"
    assert harness["machines"] == []


def test_hook_health_regresses_per_machine_under_a_held_latch(test_db):
    _seed_relay(test_db, MACHINE_A, "alpha-box")
    _seed_session(test_db, "s-a", MACHINE_A, executor="codex", surface="codex-desktop",
                  tool_calls=4)
    first = _machines(_modules()["connect_harness"])[MACHINE_A]
    assert first["state"] == "activated"
    assert _health(first)["codex"] == "green"

    # A re-keyed approval leaves the harness hookless; the latch holds.
    test_db.execute("UPDATE harness_sessions SET tool_call_count = 0")
    test_db.commit()
    again = _machines(_modules()["connect_harness"])[MACHINE_A]
    assert again["state"] == "activated"
    assert _health(again)["codex"] == "red"
