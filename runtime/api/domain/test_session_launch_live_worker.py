"""Different launch keys cannot staff duplicate workers on one item."""

import pytest

from yoke_core.domain.handlers import session_launch as handlers
from yoke_core.domain.session_launch_delivery_state import IN_FLIGHT_LAUNCH_STATES
from yoke_core.domain.work_claim_targets import make_item_target
from runtime.api.domain.session_launch_test_support import NOW
from runtime.api.domain.test_session_launch_terminal_admission import (
    _create_conn,
    _create_payload,
    _request,
    _write_counts,
)


def _create(item, key, *, composed=False):
    return handlers.handle_launch_create(
        _request(_create_payload(item, compose_mandate=composed, key=key))
    )


def _first(monkeypatch, *, composed=False):
    conn, item = _create_conn(monkeypatch, status="idea")
    first = _create(item, "first", composed=composed)
    assert first.primary_success, first.error
    return conn, item, first.result_payload["launch"]["launch_id"]


def _bind(conn, launch_id, *, state="succeeded", binding="registered_session_id"):
    conn.execute(
        "INSERT INTO harness_sessions (session_id, project_id) VALUES ('worker', 10)"
    )
    conn.execute(
        f"UPDATE session_launches SET state=?, {binding}='worker' WHERE launch_id=?",
        (state, launch_id),
    )
    conn.commit()


def _claim(conn):
    conn.execute(
        "INSERT INTO work_claims (session_id, target_kind, scope, claim_type) "
        "VALUES ('worker', 'item', ?, 'exclusive')",
        (make_item_target(41).scope_json(),),
    )
    conn.commit()


def _refused(conn, item, launch_id, *, composed=False):
    before = _write_counts(conn)
    second = _create(item, "different-key", composed=composed)
    assert not second.primary_success
    assert second.error.code == "item_has_live_worker"
    assert launch_id in second.error.message
    assert "holder session" in second.error.message
    assert _write_counts(conn) == before
    return second.error.message


@pytest.mark.parametrize("state", sorted(IN_FLIGHT_LAUNCH_STATES) + ["outcome_unknown"])
@pytest.mark.parametrize("composed", [True, False])
def test_pending_launch_refuses_different_key(monkeypatch, state, composed):
    conn, item, launch_id = _first(monkeypatch, composed=composed)
    conn.execute("UPDATE session_launches SET state=?", (state,))
    conn.commit()
    message = _refused(conn, item, launch_id, composed=composed)
    assert "no live registered session" in message
    assert f"yoke session-control launch reconcile {launch_id}" in message


@pytest.mark.parametrize("claim", [True, False])
@pytest.mark.parametrize("binding", ["registered_session_id", "native_session_id"])
def test_live_worker_refuses_different_key_with_or_without_claim(
    monkeypatch, claim, binding
):
    conn, item, launch_id = _first(monkeypatch)
    _bind(conn, launch_id, binding=binding)
    if claim:
        _claim(conn)
    message = _refused(conn, item, launch_id)
    assert "worker" in message
    assert "Wake or message" in message
    assert "yoke sessions terminate worker" in message


@pytest.mark.parametrize("composed", [True, False])
def test_same_key_replays_while_worker_holds_claim(monkeypatch, composed):
    conn, item, launch_id = _first(monkeypatch, composed=composed)
    _bind(conn, launch_id)
    _claim(conn)
    before = _write_counts(conn)
    replay = _create(item, "first", composed=composed)
    assert replay.primary_success, replay.error
    assert replay.result_payload["deduplicated"]
    assert replay.result_payload["launch"]["launch_id"] == launch_id
    assert _write_counts(conn) == before


@pytest.mark.parametrize("end_column", ["ended_at", "terminated_at"])
def test_fresh_launch_succeeds_after_worker_ended_even_with_stale_claim(
    monkeypatch, end_column
):
    conn, item, launch_id = _first(monkeypatch)
    _bind(conn, launch_id)
    _claim(conn)
    conn.execute(
        f"UPDATE harness_sessions SET {end_column}=? WHERE session_id='worker'", (NOW,)
    )
    conn.commit()
    fresh = _create(item, "fresh")
    assert fresh.primary_success, fresh.error
    assert not fresh.result_payload["deduplicated"]
    assert fresh.result_payload["launch"]["launch_id"] != launch_id


@pytest.mark.parametrize("state", ["failed", "expired", "cancelled"])
def test_terminal_launch_without_live_session_allows_fresh_worker(monkeypatch, state):
    conn, item, _ = _first(monkeypatch)
    conn.execute("UPDATE session_launches SET state=?", (state,))
    conn.commit()
    fresh = _create(item, "fresh")
    assert fresh.primary_success, fresh.error


def test_itemless_create_is_unaffected_by_item_worker(monkeypatch):
    conn, item, launch_id = _first(monkeypatch)
    _bind(conn, launch_id)
    _claim(conn)
    payload = _create_payload(item, compose_mandate=False, key="itemless")
    payload.pop("item")
    fresh = handlers.handle_launch_create(_request(payload))
    assert fresh.primary_success, fresh.error
    assert _write_counts(conn)[0] == 2


def test_item_title_change_does_not_hide_pending_launch(monkeypatch):
    conn, item, launch_id = _first(monkeypatch)
    conn.execute("UPDATE items SET title='New item title'")
    conn.commit()
    _refused(conn, item, launch_id)


def test_claim_only_live_holder_is_named(monkeypatch):
    conn, item = _create_conn(monkeypatch, status="idea")
    conn.execute(
        "INSERT INTO harness_sessions (session_id, project_id) VALUES ('worker', 10)"
    )
    _claim(conn)
    message = _refused(conn, item, "none (claim-only holder)")
    assert "worker" in message


def test_a_worker_holding_the_claim_is_told_to_release_it_first(monkeypatch):
    conn, item = _create_conn(monkeypatch, status="idea")
    conn.execute(
        "INSERT INTO work_claims (session_id, target_kind, scope, claim_type) "
        "VALUES ('caller', 'item', ?, 'exclusive')",
        (make_item_target(41).scope_json(),),
    )
    conn.commit()
    before = _write_counts(conn)
    refused = _create(item, "level-successor")
    assert not refused.primary_success
    assert refused.error.code == "item_has_live_worker"
    message = refused.error.message
    assert "You hold this item's claim yourself" in message
    assert "yoke claims work release --all-mine" in message
    assert "then retry the same command" in message
    assert "yoke sessions terminate" not in message
    assert _write_counts(conn) == before


def test_other_item_pending_launch_does_not_block(monkeypatch):
    conn, _, _ = _first(monkeypatch)
    conn.execute(
        "INSERT INTO items SELECT id+1,project_id,project_sequence+1,title,status,"
        "workflow_id,workflow_version_id FROM items"
    )
    conn.commit()
    sequence = conn.execute("SELECT MAX(project_sequence) FROM items").fetchone()[0]
    fresh = _create(f"LP-{sequence}", "other-item")
    assert fresh.primary_success, fresh.error


def test_item_lock_precedes_replay_read(monkeypatch):
    from yoke_core.domain import session_launch_assignment, session_launch_requests

    _, item, _ = _first(monkeypatch)
    locked = []
    original = session_launch_requests.get_launch_by_dedupe

    def lock(_conn, *, public_ref, project_id):
        locked.append((public_ref, project_id))

    def read(conn, actor_id, key):
        assert locked == [(item, 10)]
        return original(conn, actor_id, key)

    monkeypatch.setattr(session_launch_assignment, "lock_assigned_item", lock)
    monkeypatch.setattr(session_launch_requests, "get_launch_by_dedupe", read)
    replay = _create(item, "first")
    assert replay.primary_success, replay.error
    assert replay.result_payload["deduplicated"]
