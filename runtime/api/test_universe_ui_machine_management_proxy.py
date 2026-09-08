"""Local UI proxy coverage for machine detail and retirement."""

from __future__ import annotations

from runtime.api.universe_ui_server_test_support import (
    _TOKEN,
    ui_client as ui_client,
)


def _call(ui_client, function: str, payload: dict):
    return ui_client.post(
        f"/api/functions/call?token={_TOKEN}",
        json={"function": function, "payload": payload},
    )


def test_machine_detail_and_retirement_use_the_local_operator_path(
    ui_client,
    test_db,
    monkeypatch,
):
    from yoke_core.domain.machine_registry import register_machine
    from yoke_core.ui import local_operator_actor

    machine_id = "11111111-1111-4111-8111-111111111111"
    register_machine(
        test_db,
        machine_id=machine_id,
        name="Local studio",
        actor_id=1,
        now="2026-09-08T12:00:00Z",
    )
    monkeypatch.setattr(local_operator_actor, "resolve_local_operator_actor", lambda: 1)

    listed = _call(ui_client, "machine.list", {})
    assert listed.status_code == 200
    assert listed.json()["result"]["machines"][0]["name"] == "Local studio"
    detail = _call(ui_client, "machine.detail", {"machine_id": machine_id})
    assert detail.status_code == 200
    assert detail.json()["result"]["machine"]["machine_id"] == machine_id
    retired = _call(ui_client, "machine.retire", {"machine_id": machine_id})
    assert retired.status_code == 200
    assert retired.json()["result"]["machine"]["retired_at"] is not None
