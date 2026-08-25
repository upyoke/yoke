"""Family- and machine-derived wake routing over registered session facts."""

from __future__ import annotations

from yoke_core.domain.session_message_routing import messageability


INSTALLED_CLI = {"claude-cli": "2.1.241"}


def _row(
    *,
    surface: str = "claude-desktop",
    version: str = "1.34493.1",
    posture: str = "running",
) -> dict[str, object]:
    return {
        "executor_surface": surface,
        "executor_version": version,
        "turn_posture": posture,
    }


def test_stopped_desktop_session_wakes_through_the_installed_cli() -> None:
    routing = messageability(
        _row(),
        liveness="ended",
        machine_surface_versions=INSTALLED_CLI,
    )

    assert routing["wake_operation"] == "message_stopped"
    assert routing["wake_interface"] == "supported"
    assert routing["messageable"] is True


def test_waiting_desktop_session_wakes_through_the_installed_cli() -> None:
    routing = messageability(
        _row(posture="waiting"),
        liveness="active",
        machine_surface_versions=INSTALLED_CLI,
    )

    assert routing["wake_operation"] == "message_stopped"
    assert routing["wake_interface"] == "supported"


def test_live_and_idle_sessions_keep_their_private_surface_routes() -> None:
    active = messageability(
        _row(), liveness="active", machine_surface_versions=INSTALLED_CLI
    )
    idle = messageability(
        _row(), liveness="stale", machine_surface_versions=INSTALLED_CLI
    )

    assert active["wake_operation"] == "message_active"
    assert active["wake_interface"] == "private"
    assert idle["wake_operation"] == "message_idle"
    assert idle["wake_interface"] == "private"


def test_stopped_session_without_a_qualifying_installed_cli_has_no_route() -> None:
    for installed in ({}, {"claude-cli": "2.1.237"}, {"codex-cli": "0.149.0"}):
        routing = messageability(
            _row(), liveness="ended", machine_surface_versions=installed
        )

        assert routing["wake_operation"] == "message_stopped"
        assert routing["wake_interface"] == "none"


def test_machine_wake_survives_an_unproven_registered_surface_version() -> None:
    routing = messageability(
        _row(version="0.1.0"),
        liveness="ended",
        machine_surface_versions=INSTALLED_CLI,
    )

    assert routing["reason"] == "version_below_floor_or_unknown"
    assert routing["messageable"] is False
    assert routing["wake_operation"] == "message_stopped"
    assert routing["wake_interface"] == "supported"


def test_other_families_keep_their_own_surface_routes() -> None:
    codex = messageability(
        _row(surface="codex-cli", version="0.149.0"),
        liveness="ended",
        machine_surface_versions=INSTALLED_CLI,
    )
    unknown = messageability(
        _row(surface="invented"),
        liveness="ended",
        machine_surface_versions=INSTALLED_CLI,
    )

    assert codex["wake_interface"] == "supported"
    assert unknown == {
        "messageable": False,
        "hook_injection": False,
        "wake_interface": "none",
        "reason": "unknown_surface",
    }


def test_routing_without_machine_facts_reports_only_surface_routes() -> None:
    routing = messageability(_row(), liveness="ended")

    assert routing["wake_operation"] == "message_stopped"
    assert routing["wake_interface"] == "none"
