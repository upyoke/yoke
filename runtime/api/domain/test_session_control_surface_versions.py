"""Version-normalized native surface capability gates."""

from yoke_contracts.session_control import private_route_versions
from yoke_contracts.session_control.capabilities import (
    SESSION_SURFACE_CAPABILITIES,
)
from yoke_contracts.session_control.private_route_versions import (
    PRIVATE_ROUTE_VERSION_QUALIFICATIONS,
)
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


def test_private_route_registry_starts_with_the_existing_exact_pins() -> None:
    expected = {
        (surface, operation): frozenset({capability.minimum_version})
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
    qualifications[key] = frozenset({baseline, candidate})
    monkeypatch.setattr(
        private_route_versions,
        "PRIVATE_ROUTE_VERSION_QUALIFICATIONS",
        qualifications,
    )

    assert surface_operation_supported(key[0], baseline, key[1])
    assert surface_operation_supported(key[0], candidate, key[1])
    assert not surface_operation_supported(key[0], "2.1.240", key[1])


def test_other_private_surface_versions_remain_exactly_pinned() -> None:
    assert surface_version_supported("claude-cli", "2.1.239")
    assert surface_operation_supported("claude-cli", "2.1.238", "message_idle")
    assert not surface_operation_supported("claude-cli", "2.1.239", "message_idle")
    assert not surface_operation_supported("claude-cli", "2.1.238.0", "message_idle")
    assert not surface_operation_supported(
        "claude-cli", "2.1.238-deadbee", "message_idle"
    )
    assert surface_operation_supported("codex-cli", "0.148.0-alpha.15", "create")
    assert surface_operation_supported("codex-cli", "0.149.0", "create")
    assert not surface_operation_supported("codex-cli", "not-a-version", "create")
    assert not surface_operation_supported("cursor-cli", "2026.08.11", "delete")


def test_core_owner_module_reexports_the_contract_authority() -> None:
    assert owner_surface_operation_supported is surface_operation_supported
