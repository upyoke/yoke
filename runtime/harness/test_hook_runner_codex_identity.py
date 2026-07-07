"""Codex hook subprocess identity selection regression tests.

Lives as a focused sibling of ``test_hook_runner_runner.py`` because that file
is at the 350-line cap. These tests prove the hook runner picks the Codex
adapter (and ``detect_provider`` returns ``openai``) when the Codex hooks.json
command shape pins ``YOKE_EXECUTOR=codex`` / ``YOKE_PROVIDER=openai`` even
when ``CODEX_THREAD_ID`` is not exported into the hook subprocess — the
verified Codex Desktop failure shape.
"""

from __future__ import annotations

import pytest

from runtime.harness.codex.adapter import CAPABILITY as CODEX_CAPABILITY
from runtime.harness.claude.adapter import CAPABILITY as CLAUDE_CAPABILITY
from runtime.harness.hook_helpers_identity import (
    detect_executor,
    detect_provider,
)
from runtime.harness.hook_runner.capability_resolve import resolve_capability


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch):
    """Clear every identity / Codex env var so each test starts from zero."""
    for var in (
        "YOKE_EXECUTOR",
        "YOKE_PROVIDER",
        "CODEX_THREAD_ID",
        "CODEX_INTERNAL_ORIGINATOR_OVERRIDE",
        "CODEX_ORIGINATOR",
        "CLAUDE_CODE_ENTRYPOINT",
    ):
        monkeypatch.delenv(var, raising=False)
    yield


class TestCodexIdentityDetection:
    """Pinned env vars drive detect_executor / detect_provider correctly."""

    def test_detect_executor_returns_codex_with_pin_and_no_thread_id(
        self, clean_env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """YOKE_EXECUTOR=codex pinned in env makes detect_executor return codex,
        regardless of CODEX_THREAD_ID being missing. This is the rendered Codex
        hook command shape applied at subprocess level."""
        monkeypatch.setenv("YOKE_EXECUTOR", "codex")
        assert detect_executor() == "codex"

    def test_detect_provider_returns_openai_with_pin_and_no_thread_id(
        self, clean_env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """YOKE_PROVIDER=openai pinned in env makes detect_provider return openai
        even when CODEX_THREAD_ID is missing."""
        monkeypatch.setenv("YOKE_EXECUTOR", "codex")
        monkeypatch.setenv("YOKE_PROVIDER", "openai")
        assert detect_provider() == "openai"

    def test_detect_provider_codex_family_returns_openai_without_explicit_provider(
        self, clean_env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Even without YOKE_PROVIDER, the codex family executor implies openai."""
        monkeypatch.setenv("YOKE_EXECUTOR", "codex")
        # YOKE_PROVIDER deliberately unset
        assert detect_provider() == "openai"

    def test_without_pin_falls_back_to_claude(self, clean_env) -> None:
        """The verified Codex Desktop failure shape: without any pin or CODEX_THREAD_ID,
        detection falls through to the Claude family. This is exactly the wrong
        attribution prevented by pinning the env."""
        assert detect_executor() == "claude-code"
        assert detect_provider() == "anthropic"


class TestRunnerAdapterSelection:
    """The rendered Codex hook command shape selects the Codex adapter."""

    def test_resolve_capability_picks_codex_with_pin_and_no_thread_id(
        self, clean_env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With YOKE_EXECUTOR=codex pinned (as the rendered Codex hooks.json
        command does) and no CODEX_THREAD_ID, ``capability_resolve.resolve_capability``
        loads ``runtime.harness.codex.adapter.CAPABILITY``."""
        monkeypatch.setenv("YOKE_EXECUTOR", "codex")
        capability = resolve_capability(detect_executor(), dry_run=False)
        assert capability is CODEX_CAPABILITY
        assert capability.family == "codex"

    def test_resolve_capability_picks_codex_surface_pin(
        self, clean_env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Surface-specific overrides (codex-desktop, codex-vscode) still select
        the Codex adapter — ``resolve_capability`` keys on the codex prefix."""
        for surface in ("codex-desktop", "codex-vscode", "codex-cli"):
            monkeypatch.setenv("YOKE_EXECUTOR", surface)
            capability = resolve_capability(detect_executor(), dry_run=False)
            assert capability is CODEX_CAPABILITY, (
                f"surface {surface!r} should select the Codex adapter"
            )

    def test_resolve_capability_picks_claude_without_pin(self, clean_env) -> None:
        """Boundary check: without any Codex signal, the runner still loads the
        Claude adapter (preserves the existing Claude attribution path)."""
        capability = resolve_capability(detect_executor(), dry_run=False)
        assert capability is CLAUDE_CAPABILITY
        assert capability.family == "claude"


def test_rendered_codex_hook_command_pin_round_trips_through_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Integration: simulate ``env YOKE_EXECUTOR=codex YOKE_PROVIDER=openai ...``
    invoking the runner. We do not actually spawn a subprocess — instead we
    mutate ``os.environ`` exactly as ``env`` would have, then re-run the
    detection chain. This proves the rendered command shape, when executed,
    flows through to the Codex adapter selection."""
    # Mimic what `env YOKE_EXECUTOR=codex YOKE_PROVIDER=openai` does for the
    # python3 subprocess: YOKE_EXECUTOR and YOKE_PROVIDER are set, all
    # Codex-thread signals absent (the Desktop failure shape).
    for var in (
        "CODEX_THREAD_ID",
        "CODEX_INTERNAL_ORIGINATOR_OVERRIDE",
        "CODEX_ORIGINATOR",
        "CLAUDE_CODE_ENTRYPOINT",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("YOKE_EXECUTOR", "codex")
    monkeypatch.setenv("YOKE_PROVIDER", "openai")

    executor = detect_executor()
    provider = detect_provider()
    capability = resolve_capability(executor, dry_run=False)

    assert executor == "codex"
    assert provider == "openai"
    assert capability is CODEX_CAPABILITY
