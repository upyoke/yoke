"""Version-normalized native surface capability gates."""

from yoke_contracts.session_control.surface_versions import (
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


def test_other_private_surface_versions_remain_exactly_pinned() -> None:
    assert surface_version_supported("claude-cli", "2.1.239")
    assert surface_operation_supported("claude-cli", "2.1.238", "message_idle")
    assert not surface_operation_supported("claude-cli", "2.1.239", "message_idle")
    assert not surface_operation_supported(
        "claude-cli", "2.1.238-deadbee", "message_idle"
    )
    assert surface_operation_supported("codex-cli", "0.148.0-alpha.15", "create")
    assert surface_operation_supported("codex-cli", "0.149.0", "create")
    assert not surface_operation_supported("codex-cli", "not-a-version", "create")
    assert not surface_operation_supported("cursor-cli", "2026.08.11", "delete")


def test_core_owner_module_reexports_the_contract_authority() -> None:
    assert owner_surface_operation_supported is surface_operation_supported
