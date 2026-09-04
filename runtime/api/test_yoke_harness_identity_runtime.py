"""Regression tests for packaged harness identity helpers."""

from __future__ import annotations

import pytest

from yoke_contracts.executor_labels import surface_alias
from yoke_core.domain.sessions_lifecycle_canonicalize import canonicalize_executor
from yoke_harness.hooks import identity


@pytest.mark.parametrize(
    ("executor", "expected"),
    [
        ("codex", "codex"),
        ("codex-desktop", "codex"),
        ("claude", "claude-code"),
        ("claude-code", "claude-code"),
        ("claude-vscode", "claude-code"),
    ],
)
def test_canonical_harness_id_accepts_family_aliases(
    executor: str,
    expected: str,
) -> None:
    assert identity.canonical_harness_id(executor) == expected


def test_compose_executor_from_entrypoint_preserves_known_family() -> None:
    assert (
        identity.compose_executor_from_entrypoint("codex", "codex-desktop")
        == "codex-desktop"
    )
    assert (
        identity.compose_executor_from_entrypoint("claude-code", "desktop")
        == "claude-desktop"
    )
    assert (
        identity.compose_executor_from_entrypoint("custom", "codex-desktop") == "custom"
    )


def test_claude_print_mode_entrypoint_resolves_to_cli_surface() -> None:
    assert surface_alias("sdk-cli") == "claude-cli"
    assert (
        identity.compose_executor_from_entrypoint("claude-code", "sdk-cli")
        == "claude-cli"
    )
    assert canonicalize_executor("claude-code", "sdk-cli") == (
        "claude-code",
        "claude-cli",
    )


@pytest.mark.parametrize("value", ["unknown", "default", "<synthetic>", ""])
def test_placeholder_model_values_remain_upgradeable(value: str) -> None:
    assert identity._is_placeholder_model(value) is True
