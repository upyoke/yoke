"""New item-bound launches refuse already-terminal work before any write."""

from __future__ import annotations

from runtime.api.domain.session_launch_terminal_admission_test_support import (
    _NoCloseConnection as _NoCloseConnection,
    _create_conn as _create_conn,
    _create_payload as _create_payload,
    _pin_definition as _pin_definition,
    _request as _request,
    _seed_pinned_item as _seed_pinned_item,
    _wire_create as _wire_create,
    _write_counts as _write_counts,
)


import pytest

from yoke_core.domain.handlers import session_launch as handlers
from yoke_core.domain.session_launch_assignment import (
    assigned_item_id,
    refuse_terminal_assigned_item,
)
from yoke_core.domain.session_launch_types import SessionLaunchError
from runtime.api.domain.session_launch_test_support import (
    launch_connection,
)








def _archived_definition() -> dict:
    definition = _pin_definition()
    last = dict(definition["stages"][-1])
    last["id"] = "archived"
    definition["stages"] = [*definition["stages"][:-1], last]
    definition["terminal_stage_ids"] = ["archived"]
    return definition












@pytest.mark.parametrize(
    "status,compose_mandate",
    [
        ("cancelled", True),
        ("cancelled", False),
        ("stopped", True),
        ("stopped", False),
        ("done", True),
        ("done", False),
    ],
)
def test_terminal_create_refuses_before_any_write(monkeypatch, status, compose_mandate):
    conn, item = _create_conn(monkeypatch, status=status)
    before = _write_counts(conn)

    outcome = handlers.handle_launch_create(
        _request(_create_payload(item, compose_mandate=compose_mandate, key="term-1"))
    )

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "assignment_item_terminal"
    assert "already terminal" in outcome.error.message
    assert _write_counts(conn) == before


def test_custom_workflow_terminal_stage_is_refused(monkeypatch):
    conn, item = _create_conn(
        monkeypatch, status="archived", definition=_archived_definition()
    )
    before = _write_counts(conn)

    outcome = handlers.handle_launch_create(
        _request(_create_payload(item, compose_mandate=False, key="archived-raw"))
    )

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "assignment_item_terminal"
    assert _write_counts(conn) == before


@pytest.mark.parametrize("compose_mandate", [True, False])
def test_active_item_create_still_succeeds(monkeypatch, compose_mandate):
    conn, item = _create_conn(monkeypatch, status="idea")

    outcome = handlers.handle_launch_create(
        _request(
            _create_payload(item, compose_mandate=compose_mandate, key="active-ok")
        )
    )

    assert outcome.primary_success is True, outcome.error
    assert outcome.result_payload["deduplicated"] is False
    assert _write_counts(conn)[0] == 1


def test_same_request_idempotent_replay_returns_the_stored_launch(monkeypatch):
    conn, item = _create_conn(monkeypatch, status="idea")
    payload = _create_payload(item, compose_mandate=True, key="replay-1")

    first = handlers.handle_launch_create(_request(payload))
    second = handlers.handle_launch_create(_request(payload))

    assert first.primary_success is True
    assert second.primary_success is True
    assert second.result_payload["deduplicated"] is True
    assert (
        second.result_payload["launch"]["launch_id"]
        == first.result_payload["launch"]["launch_id"]
    )
    assert _write_counts(conn)[0] == 1


@pytest.mark.parametrize("compose_mandate", [True, False])
def test_changed_instructions_same_key_conflicts(monkeypatch, compose_mandate):
    conn, item = _create_conn(monkeypatch, status="idea")
    payload = _create_payload(
        item, compose_mandate=compose_mandate, key=f"changed-{compose_mandate}"
    )
    first = handlers.handle_launch_create(_request(payload))
    assert first.primary_success is True, first.error
    changed = {**payload, "instructions": "Different launch body."}
    second = handlers.handle_launch_create(_request(changed))
    assert second.primary_success is False
    assert second.error is not None
    assert second.error.code == "idempotency_conflict"
    assert _write_counts(conn)[0] == 1


def test_changed_raw_body_same_key_conflicts_after_item_is_terminal(monkeypatch):
    conn, item = _create_conn(monkeypatch, status="idea")
    payload = _create_payload(item, compose_mandate=False, key="chg-term-raw")
    first = handlers.handle_launch_create(_request(payload))
    assert first.primary_success is True, first.error
    conn.execute("UPDATE items SET status='cancelled' WHERE id=41")
    conn.commit()
    changed = {**payload, "instructions": "Different launch body."}
    second = handlers.handle_launch_create(_request(changed))
    assert second.primary_success is False
    assert second.error is not None
    assert second.error.code == "idempotency_conflict"
    assert _write_counts(conn)[0] == 1


def test_raw_same_request_replay_survives_item_becoming_terminal(monkeypatch):
    conn, item = _create_conn(monkeypatch, status="idea")
    payload = _create_payload(item, compose_mandate=False, key="replay-term-raw")
    first = handlers.handle_launch_create(_request(payload))
    assert first.primary_success is True, first.error
    conn.execute("UPDATE items SET status='cancelled' WHERE id=41")
    conn.commit()
    second = handlers.handle_launch_create(_request(payload))
    assert second.primary_success is True, second.error
    assert second.result_payload["deduplicated"] is True
    assert (
        second.result_payload["launch"]["launch_id"]
        == first.result_payload["launch"]["launch_id"]
    )
    assert _write_counts(conn)[0] == 1


def test_composed_replay_still_refuses_after_item_is_terminal(monkeypatch):
    conn, item = _create_conn(monkeypatch, status="idea")
    payload = _create_payload(item, compose_mandate=True, key="replay-term-composed")
    first = handlers.handle_launch_create(_request(payload))
    assert first.primary_success is True, first.error
    conn.execute("UPDATE items SET status='cancelled' WHERE id=41")
    conn.commit()
    second = handlers.handle_launch_create(_request(payload))
    assert second.primary_success is False
    assert second.error is not None
    assert second.error.code == "assignment_item_terminal"
    assert _write_counts(conn)[0] == 1


def test_assignment_name_still_names_a_terminal_item():
    conn = launch_connection()
    item = _seed_pinned_item(conn, status="archived", definition=_archived_definition())
    assert assigned_item_id(conn, public_ref=item, project_id=10) == 41


def test_refuse_terminal_uses_typed_stage_membership():
    conn = launch_connection()
    item = _seed_pinned_item(conn, status="archived", definition=_archived_definition())
    with pytest.raises(SessionLaunchError) as raised:
        refuse_terminal_assigned_item(conn, public_ref=item, project_id=10)
    assert raised.value.code == "assignment_item_terminal"
