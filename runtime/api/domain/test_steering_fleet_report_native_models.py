"""Native model availability reaching the steering seat from connected relays."""

from __future__ import annotations

import json

import pytest

from runtime.api.steering_fleet_test_helpers import (
    NOW,
    PROJECT_ID,
    compose,
    seed_steering_scope,
)
from yoke_contracts.session_control.native_models import (
    NO_ADAPTER_REASON,
    empty_reading,
    models_reading,
    native_model,
    stale_reading,
)
from yoke_core.domain.session_launch_machine_models import machine_native_models
from yoke_core.domain.steering_fleet_report_native_models import (
    NAMED_MODEL_SAMPLE,
    MachineNativeModels,
    fingerprint_material,
    load_native_models,
    native_model_lines,
)
from yoke_core.domain.steering_fleet_report_render import report_body


MACHINE = "machine-1"


@pytest.fixture
def fleet(test_db):
    return seed_steering_scope(test_db)


def _reading(*models: str, observed_at: str = NOW) -> dict[str, object]:
    return models_reading(
        "codex-cli",
        [native_model(name) for name in models],
        source="codex app-server model/list",
        observed_at=observed_at,
    )


def _publish(fleet, readings: dict[str, object]) -> None:
    fleet.execute(
        "UPDATE session_relays SET surface_native_models=%s WHERE relay_id='relay-1'",
        (json.dumps(readings),),
    )
    fleet.commit()


def test_connected_relay_availability_reaches_the_project_scope(fleet) -> None:
    _publish(
        fleet,
        {
            "codex-cli": _reading("gpt-6-astra", "gpt-5.5"),
            "codex-desktop": empty_reading(
                "codex-desktop", "unsupported", NO_ADAPTER_REASON
            ),
        },
    )

    rows = load_native_models(fleet, project_id=PROJECT_ID, now=NOW)

    by_surface = {row.surface: row for row in rows}
    assert by_surface["codex-cli"].status == "ok"
    assert by_surface["codex-cli"].model_count == 2
    assert by_surface["codex-cli"].sample_models == ("gpt-6-astra", "gpt-5.5")
    assert by_surface["codex-cli"].machine_id == MACHINE
    # The desktop surface is carried rather than dropped, so a reader never
    # infers that the CLI's answer covers the app beside it.
    assert by_surface["codex-desktop"].status == "unsupported"


def test_a_relay_serving_another_project_is_not_reported_here(fleet) -> None:
    _publish(fleet, {"codex-cli": _reading("gpt-5.5")})
    fleet.execute(
        "UPDATE session_relays SET project_checkouts=%s WHERE relay_id='relay-1'",
        (json.dumps([PROJECT_ID + 500]),),
    )
    fleet.commit()

    assert load_native_models(fleet, project_id=PROJECT_ID, now=NOW) == ()


def test_a_silent_relay_stops_being_reported(fleet) -> None:
    _publish(fleet, {"codex-cli": _reading("gpt-5.5")})
    fleet.execute(
        "UPDATE session_relays SET connected_until=%s WHERE relay_id='relay-1'",
        ("2026-08-01T00:00:00Z",),
    )
    fleet.commit()

    assert load_native_models(fleet, project_id=PROJECT_ID, now=NOW) == ()


def test_stale_rows_still_carry_models_into_the_report(fleet) -> None:
    # A momentarily unreachable surface has not withdrawn its models, and the
    # seat still needs to know what it can request there.
    _publish(
        fleet,
        {
            "codex-cli": stale_reading(
                _reading("gpt-6-astra"), "codex-cli", "app_server_timeout"
            )
        },
    )

    row = load_native_models(fleet, project_id=PROJECT_ID, now=NOW)[0]

    assert row.status == "stale"
    assert row.carries_models
    assert row.sample_models == ("gpt-6-astra",)


def test_machine_read_returns_the_latest_heartbeat_for_selection(fleet) -> None:
    _publish(fleet, {"codex-cli": _reading("gpt-5.5")})

    readings = machine_native_models(fleet, machine_id=MACHINE)

    assert readings["codex-cli"]["status"] == "ok"
    assert [entry["model"] for entry in readings["codex-cli"]["models"]] == ["gpt-5.5"]


def test_a_machine_with_no_relay_row_reports_nothing_rather_than_raising(
    fleet,
) -> None:
    assert machine_native_models(fleet, machine_id="machine-absent") == {}


def test_the_report_body_names_what_each_machine_can_select(fleet) -> None:
    _publish(fleet, {"codex-cli": _reading("gpt-6-astra", "gpt-5.5")})

    body = report_body(compose(fleet))

    assert "selectable models (observed natively)" in body
    assert "codex-cli: 2 — gpt-6-astra, gpt-5.5" in body


def _row(**overrides) -> MachineNativeModels:
    fields = {
        "machine_id": MACHINE,
        "machine_name": "workbox",
        "surface": "codex-cli",
        "status": "ok",
        "reason": None,
        "source": "codex app-server model/list",
        "observed_at": NOW,
        "model_count": 2,
        "sample_models": ("gpt-6-astra", "gpt-5.5"),
    }
    fields.update(overrides)
    return MachineNativeModels(**fields)


def test_render_names_the_models_and_says_when_they_went_stale() -> None:
    lines = native_model_lines((_row(), _row(surface="cursor-cli", status="stale")))

    assert lines[0] == "  selectable models (observed natively):"
    assert "codex-cli: 2 — gpt-6-astra, gpt-5.5" in lines[1]
    assert f"stale since {NOW}" in lines[2]


def test_render_summarizes_a_long_listing_rather_than_printing_all_of_it() -> None:
    sample = tuple(f"model-{index}" for index in range(NAMED_MODEL_SAMPLE))

    lines = native_model_lines((_row(model_count=211, sample_models=sample),))

    assert f"+{211 - NAMED_MODEL_SAMPLE} more" in lines[1]


def test_render_omits_declared_absences_but_keeps_a_surface_that_failed() -> None:
    assert native_model_lines((_row(status="unsupported", model_count=0),)) == []

    lines = native_model_lines(
        (_row(status="unknown", model_count=0, reason="app_server_timeout"),)
    )

    assert lines[1].endswith("codex-cli: unknown — app_server_timeout")


def test_a_new_model_changes_the_fingerprint_so_the_seat_is_told() -> None:
    before = fingerprint_material((_row(),))
    after = fingerprint_material(
        (_row(model_count=3, sample_models=("gpt-6-astra", "gpt-5.5", "gpt-7")),)
    )

    assert before != after


def test_a_surface_going_stale_changes_the_fingerprint() -> None:
    assert fingerprint_material((_row(),)) != fingerprint_material(
        (_row(status="stale", reason="app_server_timeout"),)
    )
