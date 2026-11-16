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


def test_parent_model_probe_preserves_windows_argv(monkeypatch):
    from yoke_contracts.platform_process import ProcessInfo
    from yoke_harness.hooks import identity_runtime
    from yoke_core.hooks import helpers_model
    entries = [ProcessInfo(42, 1, (r"C:\Program Files\Claude\claude.exe", "--model", "chosen"),
                           123.5, "claude.exe", 10, "owner")]
    for owner in (identity_runtime, helpers_model):
        monkeypatch.setattr(owner.os, "getppid", lambda: 42)
        monkeypatch.setattr(owner.platform_process, "process_command_lines", lambda: entries)
        assert owner._read_parent_argv() == list(entries[0].cmdline)
        assert owner._extract_model_from_argv(owner._read_parent_argv()) == "chosen"
