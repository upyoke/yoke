"""Overview setup completion for people with live and retired machines."""

from runtime.api.domain.overview_machine_activation_test_support import (
    MACHINE_A,
    _seed_relay,
    _seed_session,
)
from runtime.api.test_overview_activation_machines import MACHINE_B, _machines, _modules
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain import overview_machine_activation
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.overview_activation_read import latch_run_onboard

WIZARD = "finish_installation_wizard"
HARNESS = "connect_harness"
ONBOARD = "run_onboard"
HOST_FACTS = {"host_facts": {"machine_connected": False}}


def _member(conn, label):
    actor_id = seed_human_actor(conn, label)
    conn.commit()
    return actor_id


def _viewer_modules(actor_id):
    return _modules(HOST_FACTS, actor_id=str(actor_id))


def test_connected_machine_completes_viewer_setup_with_a_pending_machine(test_db):
    owner = _member(test_db, "owner")
    _seed_relay(test_db, MACHINE_A, "connected", actor_id=owner)
    _seed_relay(test_db, MACHINE_B, "pending", actor_id=owner)
    _seed_session(test_db, "owner-harness", MACHINE_A, actor_id=owner)

    modules = _viewer_modules(owner)
    harness = modules[HARNESS]
    rows = _machines(harness)
    assert harness["state"] == "activated"
    assert harness["activated_at"] == rows[MACHINE_A]["activated_at"]
    assert rows[MACHINE_B]["state"] == "in_progress"
    assert rows[MACHINE_B]["connected"] is None
    assert modules[ONBOARD]["state"] == "in_progress"


def test_retirement_keeps_both_steps_complete_with_the_same_times(test_db):
    owner = _member(test_db, "owner")
    _seed_relay(test_db, MACHINE_A, "original", actor_id=owner)
    _seed_session(test_db, "owner-harness", MACHINE_A, actor_id=owner)
    before = _viewer_modules(owner)

    test_db.execute(
        "UPDATE machines SET retired_at = %s WHERE machine_id = %s",
        (iso8601_now(), MACHINE_A),
    )
    test_db.commit()
    retired_only = _viewer_modules(owner)
    _seed_relay(test_db, MACHINE_B, "replacement", actor_id=owner)
    with_replacement = _viewer_modules(owner)

    for modules in (retired_only, with_replacement):
        for step in (WIZARD, HARNESS):
            assert modules[step]["state"] == "activated"
            assert before[step]["activated_at"]
            assert modules[step]["activated_at"] == before[step]["activated_at"]
    assert retired_only[HARNESS]["machines"] == []
    rows = _machines(with_replacement[HARNESS])
    assert list(rows) == [MACHINE_B]
    assert rows[MACHINE_B]["state"] == "in_progress"


def test_second_connection_preserves_viewers_earliest_timestamp(test_db, monkeypatch):
    owner = _member(test_db, "owner")
    _seed_relay(test_db, MACHINE_A, "first", actor_id=owner)
    _seed_relay(test_db, MACHINE_B, "second", actor_id=owner)
    latch_times = iter(map(parse_instant, ("2026-11-23T00:00:00Z", "2026-11-24T00:00:00Z")))
    monkeypatch.setattr(overview_machine_activation, "utc_now", lambda: next(latch_times))
    _seed_session(test_db, "first-harness", MACHINE_A, actor_id=owner)
    first = _viewer_modules(owner)[HARNESS]
    _seed_session(test_db, "second-harness", MACHINE_B, actor_id=owner)

    both = _viewer_modules(owner)[HARNESS]
    rows = _machines(both)
    assert both["state"] == "activated"
    assert all(row["state"] == "activated" for row in rows.values())
    assert both["activated_at"] == first["activated_at"]
    assert both["activated_at"] == rows[MACHINE_A]["activated_at"]
    assert rows[MACHINE_A]["activated_at"] < rows[MACHINE_B]["activated_at"]


def test_invitee_shares_onboard_completion_only(test_db):
    owner = _member(test_db, "owner")
    invitee = _member(test_db, "invitee")
    _seed_relay(test_db, MACHINE_A, "owner-machine", actor_id=owner)
    _seed_session(test_db, "owner-harness", MACHINE_A, actor_id=owner)
    onboard_at = latch_run_onboard(test_db, True)
    owner_modules = _viewer_modules(owner)
    for step in (WIZARD, HARNESS, ONBOARD):
        assert owner_modules[step]["state"] == "activated"

    invitee_modules = _viewer_modules(invitee)
    wizard, harness, onboard = (invitee_modules[key] for key in (WIZARD, HARNESS, ONBOARD))
    assert wizard["state"] == "in_progress"
    assert wizard["activated_at"] is None
    assert wizard["submodules"][0]["machines"] == []
    assert harness["state"] == "not_started"
    assert harness["activated_at"] is None
    assert onboard["state"] == "activated"
    assert onboard["activated_at"] == onboard_at
