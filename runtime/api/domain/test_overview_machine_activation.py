"""The registered-machine read and the per-machine activation latch.

A universe is shared by many machines and many members. The read lists the
viewing actor's own machines with the harnesses that ran from each, and the
latch is monotone per (machine, module), so a second box never inherits the
first box's connection history.
"""

from __future__ import annotations

from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.overview_machine_activation import (
    MACHINE_MODULE_CONNECT_HARNESS,
    MACHINE_MODULE_MACHINE_CONNECTED,
    every_machine_has_harness,
    latch_machine_activations,
    machine_module_rows,
    read_registered_machines,
)

MACHINE_A = "11111111-1111-4111-8111-111111111111"
MACHINE_B = "22222222-2222-4222-8222-222222222222"


def _actor(conn):
    """A distinct member of the same universe."""
    actor_id = int(conn.execute(
        "INSERT INTO actors (kind, created_at) "
        "VALUES ('human', %s) RETURNING id", (iso8601_now(),),
    ).fetchone()[0])
    conn.commit()
    return actor_id


def _seed_relay(conn, machine_id, hostname, *, state="active", surfaces=None,
                seen="2026-08-01T00:00:00Z", actor_id=None):
    actor = actor_id if actor_id is not None else conn.execute(
        "SELECT id FROM actors ORDER BY id LIMIT 1"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO session_relays (relay_id, actor_id, machine_id, hostname, "
        "surface_versions, project_checkouts, first_seen_at, last_seen_at, "
        "connected_until, state) VALUES (%s, %s, %s, %s, %s, '[]', %s, %s, %s, %s)",
        (
            f"machine:{machine_id}", actor, machine_id, hostname,
            surfaces or '{"claude-cli": "2.1"}', seen, seen, seen, state,
        ),
    )
    conn.commit()


def _seed_session(conn, session_id, machine_id, *, executor="claude-code",
                  surface="claude-cli", at=None, tool_calls=0, actor_id=None):
    at = at or iso8601_now()
    conn.execute(
        "INSERT INTO harness_sessions (session_id, executor, executor_surface, "
        "machine_id, provider, model, workspace, project_id, mode, offered_at, "
        "last_heartbeat, tool_call_count, actor_id) "
        "VALUES (%s, %s, %s, %s, 'anthropic', 'm', '/w', 1, 'wait', %s, %s, %s, %s)",
        (session_id, executor, surface, machine_id, at, at, tool_calls, actor_id),
    )
    conn.commit()


def test_two_machines_read_their_own_harness_history(test_db):
    _seed_relay(test_db, MACHINE_A, "alpha-box")
    _seed_relay(test_db, MACHINE_B, "beta-box", seen="2026-08-02T00:00:00Z")
    _seed_session(test_db, "s-a1", MACHINE_A, at="2026-08-01T01:00:00Z")
    _seed_session(
        test_db, "s-a2", MACHINE_A, executor="codex", surface="codex-cli",
        at="2026-08-01T02:00:00Z", tool_calls=3,
    )

    machines = {row["machine_id"]: row for row in read_registered_machines(test_db)}

    alpha = machines[MACHINE_A]
    assert alpha["name"] == "alpha-box"
    assert alpha["surfaces"] == ["claude-cli"]
    assert [h["executor"] for h in alpha["harnesses"]] == ["codex", "claude-code"]
    assert alpha["connected"] == {"executor": "codex", "at": "2026-08-01T02:00:00Z"}
    assert alpha["last_seen_at"] == "2026-08-01T02:00:00Z"
    # Surfaced sessions light their family and their exact alias; every
    # other supported surface still answers, as not installed.
    hits = {t["key"] for t in alpha["targets"] if t["hit"]}
    assert hits == {"claude-code", "codex", "claude-cli", "codex-cli"}
    statuses = {t["key"]: t["status"] for t in alpha["targets"]}
    assert statuses["cursor-desktop"] == "not_installed"
    # Those sessions are older than the telemetry window, so they read as
    # history rather than as a harness working right now.
    assert statuses["codex"] == "installed_last_seen"
    # The relay-only machine reports its installed surface without borrowing
    # the first machine's session history.
    beta = machines[MACHINE_B]
    assert beta["name"] == "beta-box"
    assert beta["harnesses"] == []
    assert beta["connected"] is None
    # Its one installed surface, and the family that surface belongs to.
    assert [
        (target["key"], target["hit"], target["hook_health"], target["status"])
        for target in beta["targets"] if target["status"] != "not_installed"
    ] == [
        ("claude-code", False, "orange", "installed_never_seen"),
        ("claude-cli", False, "orange", "installed_never_seen"),
    ]
    # The relay named a version for that surface; the card gets to show it.
    versions = {t["key"]: t["version"] for t in beta["targets"]}
    assert versions["claude-cli"] == "2.1"
    assert versions["cursor-cli"] is None
    assert beta["registered_at"] == "2026-08-02T00:00:00Z"


def test_a_machine_known_only_from_sessions_lists_without_a_name(test_db):
    _seed_session(test_db, "s-b", MACHINE_B, at="2026-08-03T00:00:00Z")

    [machine] = read_registered_machines(test_db)

    assert machine["machine_id"] == MACHINE_B
    assert machine["name"] is None
    assert machine["surfaces"] == []
    assert machine["registered_at"] == "2026-08-03T00:00:00Z"


def test_sessions_without_a_machine_id_attribute_to_no_machine(test_db):
    test_db.execute(
        "INSERT INTO harness_sessions (session_id, executor, provider, model, "
        "workspace, project_id, mode, offered_at, last_heartbeat) "
        "VALUES ('s-legacy', 'cursor', 'x', 'm', '/w', 1, 'wait', %s, %s)",
        (iso8601_now(), iso8601_now()),
    )
    test_db.commit()

    assert read_registered_machines(test_db) == []


def test_a_revoked_relay_with_no_sessions_leaves_the_list(test_db):
    _seed_relay(test_db, MACHINE_A, "gone-box", state="revoked")
    _seed_relay(test_db, MACHINE_B, "kept-box", state="revoked")
    _seed_session(test_db, "s-b", MACHINE_B)

    assert [m["machine_id"] for m in read_registered_machines(test_db)] == [MACHINE_B]


def test_latch_is_monotone_per_machine_and_module(test_db):
    _seed_relay(test_db, MACHINE_A, "alpha-box")
    _seed_relay(test_db, MACHINE_B, "beta-box")
    _seed_session(test_db, "s-a", MACHINE_A)

    rows = {
        row["machine_id"]: row
        for row in machine_module_rows(test_db, read_registered_machines(test_db))
    }
    assert rows[MACHINE_A]["connected_at"] and rows[MACHINE_A]["harness_activated_at"]
    assert rows[MACHINE_B]["connected_at"] and rows[MACHINE_B]["harness_activated_at"] is None
    assert every_machine_has_harness(list(rows.values())) is False
    first = rows[MACHINE_A]["harness_activated_at"]

    # The signal disappears; the latch does not.
    test_db.execute("DELETE FROM harness_sessions")
    test_db.commit()
    again = {
        row["machine_id"]: row
        for row in machine_module_rows(test_db, read_registered_machines(test_db))
    }
    assert again[MACHINE_A]["harness_activated_at"] == first
    assert again[MACHINE_B]["harness_activated_at"] is None

    stored = test_db.execute(
        "SELECT machine_id, module_key FROM overview_machine_activation_facts "
        "ORDER BY machine_id, module_key"
    ).fetchall()
    assert [(str(r[0]), str(r[1])) for r in stored] == [
        (MACHINE_A, MACHINE_MODULE_CONNECT_HARNESS),
        (MACHINE_A, MACHINE_MODULE_MACHINE_CONNECTED),
        (MACHINE_B, MACHINE_MODULE_MACHINE_CONNECTED),
    ]


def test_latch_write_is_idempotent(test_db):
    satisfied = {MACHINE_A: {MACHINE_MODULE_CONNECT_HARNESS: True}}
    first = latch_machine_activations(test_db, satisfied)
    second = latch_machine_activations(test_db, satisfied)
    assert first == second
    count = test_db.execute(
        "SELECT COUNT(*) FROM overview_machine_activation_facts"
    ).fetchone()[0]
    assert int(count) == 1


def test_another_members_machine_never_renders_for_this_viewer(test_db):
    """A relay names its owner, and only the owner is shown their box."""
    viewer = _actor(test_db)
    other = _actor(test_db)
    _seed_relay(test_db, MACHINE_A, "mine-box", actor_id=viewer)
    _seed_relay(test_db, MACHINE_B, "theirs-box", actor_id=other)

    mine = read_registered_machines(test_db, actor_id=viewer)
    theirs = read_registered_machines(test_db, actor_id=other)
    unscoped = read_registered_machines(test_db)

    assert [row["machine_id"] for row in mine] == [MACHINE_A]
    assert [row["machine_id"] for row in theirs] == [MACHINE_B]
    # A universe with no bound viewer keeps listing every machine.
    assert [row["machine_id"] for row in unscoped] == [MACHINE_A, MACHINE_B]


def test_a_relayless_machine_is_read_from_the_viewers_own_sessions(test_db):
    """No relay to name an owner, so the sessions that ran there decide."""
    viewer = _actor(test_db)
    other = _actor(test_db)
    _seed_session(test_db, "s-mine", MACHINE_A, actor_id=viewer)
    _seed_session(test_db, "s-theirs", MACHINE_B, actor_id=other)

    assert [
        row["machine_id"] for row in read_registered_machines(test_db, actor_id=viewer)
    ] == [MACHINE_A]


def test_hook_report_evidence_is_read_per_machine(test_db):
    """One machine's unapproved hooks never paint another machine's card."""
    viewer = _actor(test_db)
    _seed_relay(test_db, MACHINE_A, "alpha-box", actor_id=viewer,
                surfaces='{"codex-cli": "0.1"}')
    _seed_relay(test_db, MACHINE_B, "beta-box", actor_id=viewer,
                seen="2026-08-02T00:00:00Z", surfaces='{"codex-cli": "0.1"}')
    reports = [{
        "machine_id": MACHINE_A, "harness_id": "codex",
        "config_present": True, "approval_state": "unapproved",
    }]

    machines = {
        row["machine_id"]: row
        for row in read_registered_machines(test_db, reports, actor_id=viewer)
    }

    def status(machine_id, key):
        return next(
            target["status"] for target in machines[machine_id]["targets"]
            if target["key"] == key
        )

    assert status(MACHINE_A, "codex") == "hooks_need_trust"
    assert status(MACHINE_B, "codex") == "installed_never_seen"
