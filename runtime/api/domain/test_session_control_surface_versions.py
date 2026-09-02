"""Version-normalized native surface capability gates."""

import pytest

from yoke_contracts.session_control import private_route_versions
from yoke_contracts.session_control.capabilities import (
    SESSION_SURFACE_CAPABILITIES,
)
from yoke_contracts.session_control.private_route_versions import (
    PRIVATE_ROUTE_VERSION_QUALIFICATIONS,
    PrivateRouteVersionQualification,
)
from yoke_contracts.session_control.surface_versions import (
    machine_stopped_wake_supported,
    machine_wake_surface,
    surface_operation_supported,
    surface_version_supported,
)
from yoke_core.domain.session_relay_versions import (
    surface_operation_supported as owner_surface_operation_supported,
)


def test_cursor_date_build_versions_preserve_closed_operation_facts() -> None:
    observed = "2026.08.11-e8db854"

    assert surface_operation_supported("cursor-cli", observed, "create")
    assert surface_operation_supported("cursor-cli", observed, "message_idle")
    assert surface_operation_supported("cursor-cli", observed, "message_stopped")
    assert not surface_operation_supported("cursor-cli", observed, "message_active")
    assert not surface_operation_supported("cursor-desktop", "3.17.8", "create")
    assert not surface_operation_supported(
        "cursor-desktop", "3.17.8", "message_stopped"
    )


def test_cursor_build_normalization_accepts_only_the_observed_hash_family() -> None:
    assert surface_version_supported("cursor-cli", "2026.08.11-e8db854")
    assert surface_operation_supported(
        "cursor-cli", "2026.08.12-deadbee", "message_stopped"
    )
    assert not surface_operation_supported(
        "cursor-cli", "2026.08.10-deadbee", "message_stopped"
    )
    assert not surface_operation_supported(
        "cursor-cli", "2026.08.11-nothex", "message_stopped"
    )
    assert not surface_operation_supported(
        "cursor-cli", "2026.08.11-e8db85", "message_stopped"
    )
    assert not surface_version_supported("cursor-cli", "2026.08.11-nothex")


def test_codex_cli_build_revision_only_affects_capability_comparison() -> None:
    observed = "0.149.0-alpha.4.3"

    assert surface_version_supported("codex-cli", observed)
    assert surface_operation_supported("codex-cli", observed, "create")
    assert surface_operation_supported("codex-cli", observed, "message_stopped")
    assert not surface_operation_supported("codex-cli", observed, "message_active")
    assert not surface_operation_supported("codex-cli", observed, "message_idle")
    for malformed in (
        "0.149.0-alpha.4.3.1",
        "0.149.0-alpha.4.x",
        "0.149.0-alpha.4.",
    ):
        assert not surface_version_supported("codex-cli", malformed)


def test_desktop_create_contract_matches_external_writer_capabilities() -> None:
    for surface, version in (
        ("claude-desktop", "1.32885.1"),
        ("codex-desktop", "26.814.41407"),
    ):
        assert not surface_operation_supported(surface, version, "create")
    for operation in ("message_active", "message_idle", "message_stopped"):
        assert not surface_operation_supported(
            "codex-desktop", "26.814.41407", operation
        )


def test_private_route_registry_uses_floors_for_every_private_route() -> None:
    expected = {
        (surface, operation): PrivateRouteVersionQualification.surface_floor()
        for surface, capability in SESSION_SURFACE_CAPABILITIES.items()
        for operation in (
            "create",
            "message_active",
            "message_idle",
            "message_stopped",
        )
        if getattr(capability, operation) == "private"
    }

    assert dict(PRIVATE_ROUTE_VERSION_QUALIFICATIONS) == expected


def test_private_route_registry_can_retain_multiple_exact_versions(
    monkeypatch,
) -> None:
    key = ("claude-cli", "message_idle")
    baseline = SESSION_SURFACE_CAPABILITIES[key[0]].minimum_version
    candidate = "2.1.239"
    qualifications = dict(PRIVATE_ROUTE_VERSION_QUALIFICATIONS)
    qualifications[key] = PrivateRouteVersionQualification.exact(baseline, candidate)
    monkeypatch.setattr(
        private_route_versions,
        "PRIVATE_ROUTE_VERSION_QUALIFICATIONS",
        qualifications,
    )

    assert surface_operation_supported(key[0], baseline, key[1])
    assert surface_operation_supported(key[0], candidate, key[1])
    assert not surface_operation_supported(key[0], "2.1.240", key[1])


def test_desktop_active_message_uses_the_surface_minimum_version_floor() -> None:
    qualification = PRIVATE_ROUTE_VERSION_QUALIFICATIONS[
        ("claude-desktop", "message_active")
    ]

    assert qualification.uses_surface_floor
    assert surface_operation_supported("claude-desktop", "1.32885.1", "message_active")
    assert surface_operation_supported("claude-desktop", "1.34493.1", "message_active")
    assert not surface_operation_supported(
        "claude-desktop", "1.32885.0", "message_active"
    )


@pytest.mark.parametrize(
    ("surface", "operation", "floor", "newer", "below_floor"),
    (
        ("claude-cli", "message_active", "2.1.238", "2.1.239", "2.1.237"),
        ("claude-cli", "message_idle", "2.1.238", "2.1.239", "2.1.237"),
        (
            "claude-desktop",
            "message_idle",
            "1.32885.1",
            "1.32885.2",
            "1.32885.0",
        ),
        ("claude-vscode", "message_idle", "2.1.238", "2.1.239", "2.1.237"),
    ),
)
def test_private_routes_accept_newer_patch_versions(
    surface: str,
    operation: str,
    floor: str,
    newer: str,
    below_floor: str,
) -> None:
    assert surface_operation_supported(surface, floor, operation)
    assert surface_operation_supported(surface, newer, operation)
    assert not surface_operation_supported(surface, below_floor, operation)


def test_public_routes_keep_surface_strict_while_accepting_version_floors() -> None:
    assert surface_operation_supported("codex-cli", "0.148.0-alpha.15", "create")
    assert surface_operation_supported("codex-cli", "0.149.0", "create")
    assert not surface_operation_supported("codex-cli", "not-a-version", "create")
    assert not surface_operation_supported("cursor-cli", "2026.08.11", "delete")


def test_desktop_create_stays_closed() -> None:
    for surface in ("claude-desktop", "codex-desktop", "cursor-desktop"):
        capability = SESSION_SURFACE_CAPABILITIES[surface]
        assert capability.create == "none"
        assert not surface_operation_supported(
            surface, capability.minimum_version, "create"
        )


def test_documented_cli_resume_and_idle_routes_use_version_floors() -> None:
    assert surface_operation_supported("claude-cli", "2.1.238", "message_stopped")
    assert surface_operation_supported("claude-cli", "2.1.241", "message_stopped")
    assert not surface_operation_supported("claude-cli", "2.1.237", "message_stopped")
    assert surface_operation_supported("claude-cli", "2.1.241", "message_idle")
    assert not surface_operation_supported("claude-cli", "2.1.237", "message_idle")
    assert ("claude-cli", "message_stopped") not in PRIVATE_ROUTE_VERSION_QUALIFICATIONS


def test_installed_cli_wakes_every_stopped_claude_surface_it_may_wake() -> None:
    installed = {"claude-cli": "2.1.241"}

    for surface in ("claude-cli", "claude-vscode"):
        assert machine_stopped_wake_supported(surface, installed)
    assert not machine_stopped_wake_supported("codex-desktop", installed)
    assert not machine_stopped_wake_supported("cursor-desktop", installed)


def test_a_desktop_surface_has_no_peer_wake_route_at_any_installed_version() -> None:
    """Sharing a transcript store is what makes the fork possible, not allowed.

    The installed CLI can technically resume a desktop conversation, which
    is exactly why the executor is refused by name: a wake there lands in a
    copy of the window its operator is reading.
    """
    installed = {"claude-cli": "2.1.241", "cursor-cli": "2026.08.11-e8db854"}

    for surface in ("claude-desktop", "codex-desktop", "cursor-desktop"):
        assert not machine_stopped_wake_supported(surface, installed)
        assert machine_wake_surface(surface, installed, "message_idle") is None
        assert machine_wake_surface(surface, installed, "message_stopped") is None


def test_machine_wake_reads_the_installed_binary_not_the_registered_surface() -> None:
    assert not machine_stopped_wake_supported(
        "claude-vscode", {"claude-vscode": "2.1.241"}
    )
    assert not machine_stopped_wake_supported(
        "claude-vscode", {"claude-cli": "2.1.237"}
    )
    assert not machine_stopped_wake_supported("claude-vscode", {})
    assert not machine_stopped_wake_supported("claude-vscode", None)
    assert not machine_stopped_wake_supported(None, {"claude-cli": "2.1.241"})


def test_core_owner_module_reexports_the_contract_authority() -> None:
    assert owner_surface_operation_supported is surface_operation_supported
