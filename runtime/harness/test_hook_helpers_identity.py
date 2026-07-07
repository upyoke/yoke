"""Executor / provider / predicate / entrypoint detection tests.

Companion to ``test_hook_helpers.py`` (which keeps the lower-level
project/db/session/marker/json helpers). Shared fixtures live in
``conftest.py``.
"""

from __future__ import annotations

import os
from unittest import mock

import pytest

from runtime.harness.hook_helpers import (
    canonical_harness_id,
    compose_executor_from_entrypoint,
    detect_entrypoint,
    detect_executor,
    detect_provider,
    is_claude,
    is_codex,
)


# ---------------------------------------------------------------------------
# detect_executor
# ---------------------------------------------------------------------------


class TestDetectExecutor:
    def test_yoke_executor_env(self):
        with mock.patch.dict(os.environ, {"YOKE_EXECUTOR": "custom"}):
            assert detect_executor() == "custom"

    def test_codex_coarse_fallback(self):
        # Coarse fallback path — Codex thread with no
        # originator env probe resolves to the coarse `codex` value.
        with mock.patch.dict(
            os.environ,
            {"CODEX_THREAD_ID": "t123"},
            clear=True,
        ):
            assert detect_executor() == "codex"

    def test_claude_coarse_fallback(self):
        # Coarse fallback path — Claude Code with no
        # CLAUDE_CODE_ENTRYPOINT resolves to the coarse `claude-code` value.
        with mock.patch.dict(os.environ, {}, clear=True):
            assert detect_executor() == "claude-code"

    def test_claude_desktop_entrypoint(self):
        # CLAUDE_CODE_ENTRYPOINT=claude-desktop produces
        # `claude-desktop` in the executor column.
        with mock.patch.dict(
            os.environ,
            {"CLAUDE_CODE_ENTRYPOINT": "claude-desktop"},
            clear=True,
        ):
            assert detect_executor() == "claude-desktop"

    def test_claude_vscode_entrypoint(self):
        # CLAUDE_CODE_ENTRYPOINT=claude-vscode produces
        # `claude-vscode` in the executor column.
        with mock.patch.dict(
            os.environ,
            {"CLAUDE_CODE_ENTRYPOINT": "claude-vscode"},
            clear=True,
        ):
            assert detect_executor() == "claude-vscode"

    def test_claude_cli_entrypoint_gets_family_prefix(self):
        # A bare `cli` entrypoint (hypothetical future CLI surface) is
        # promoted to the `claude-cli` surface value.
        with mock.patch.dict(
            os.environ,
            {"CLAUDE_CODE_ENTRYPOINT": "cli"},
            clear=True,
        ):
            assert detect_executor() == "claude-cli"

    def test_codex_originator_override_env(self):
        # Codex env-probe (CODEX_INTERNAL_ORIGINATOR_OVERRIDE)
        # produces `codex-{surface}` values.
        with mock.patch.dict(
            os.environ,
            {
                "CODEX_THREAD_ID": "t123",
                "CODEX_INTERNAL_ORIGINATOR_OVERRIDE": "codex_cli",
            },
            clear=True,
        ):
            assert detect_executor() == "codex-cli"

    def test_codex_originator_env_fallback(self):
        # Env probe also consults CODEX_ORIGINATOR.
        with mock.patch.dict(
            os.environ,
            {
                "CODEX_THREAD_ID": "t123",
                "CODEX_ORIGINATOR": "codex_vscode",
            },
            clear=True,
        ):
            assert detect_executor() == "codex-vscode"

    def test_codex_executor_uses_full_entrypoint_resolver(self):
        # When env signals miss, executor detection still
        # consults the transcript/cache-backed resolver.
        with mock.patch.dict(
            os.environ,
            {"CODEX_THREAD_ID": "t123"},
            clear=True,
        ):
            with mock.patch(
                "runtime.harness.codex.codex_model.resolve_entrypoint",
                return_value="codex-desktop",
            ) as resolver:
                assert detect_executor() == "codex-desktop"
                resolver.assert_called_once_with()

    def test_codex_bare_surface_gets_family_prefix(self):
        # Originator that doesn't already start with `codex` gets the prefix
        # added — e.g. a hypothetical future origin `jetbrains` -> `codex-jetbrains`.
        with mock.patch.dict(
            os.environ,
            {
                "CODEX_THREAD_ID": "t123",
                "CODEX_INTERNAL_ORIGINATOR_OVERRIDE": "jetbrains",
            },
            clear=True,
        ):
            assert detect_executor() == "codex-jetbrains"


# ---------------------------------------------------------------------------
# detect_provider
# ---------------------------------------------------------------------------


class TestDetectProvider:
    def test_yoke_provider_env(self):
        with mock.patch.dict(os.environ, {"YOKE_PROVIDER": "custom"}):
            assert detect_provider() == "custom"

    def test_codex_coarse_returns_openai(self):
        # Coarse-fallback input; predicate still matches.
        assert detect_provider("codex") == "openai"

    def test_codex_surface_returns_openai(self):
        # is_codex predicate returns True for any codex-* surface,
        # so the provider stays `openai`.  Clear env so a stray
        # YOKE_PROVIDER override from a sibling test cannot mask the result.
        with mock.patch.dict(os.environ, {}, clear=True):
            assert detect_provider("codex-desktop") == "openai"
            assert detect_provider("codex-vscode") == "openai"
            assert detect_provider("codex-cli") == "openai"

    def test_claude_surface_returns_anthropic(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            assert detect_provider("claude-desktop") == "anthropic"
            assert detect_provider("claude-vscode") == "anthropic"

    def test_default_anthropic(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            assert detect_provider() == "anthropic"


# ---------------------------------------------------------------------------
# is_codex / is_claude predicates
# ---------------------------------------------------------------------------


class TestExecutorPredicates:
    # is_codex / is_claude return true for coarse values and
    # for any `{family}-*` variant.
    def test_is_codex_coarse(self):
        assert is_codex("codex") is True

    def test_is_codex_surfaces(self):
        assert is_codex("codex-desktop") is True
        assert is_codex("codex-vscode") is True
        assert is_codex("codex-cli") is True
        assert is_codex("codex-future-surface") is True

    def test_is_codex_rejects_non_codex(self):
        assert is_codex("claude-code") is False
        assert is_codex("claude-desktop") is False
        assert is_codex(None) is False
        assert is_codex("") is False
        assert is_codex("acme-bot") is False

    def test_is_claude_coarse(self):
        assert is_claude("claude") is True
        assert is_claude("claude-code") is True

    def test_is_claude_surfaces(self):
        assert is_claude("claude-desktop") is True
        assert is_claude("claude-vscode") is True
        assert is_claude("claude-cli") is True
        assert is_claude("claude-bedrock") is True  # hypothetical future surface

    def test_is_claude_rejects_non_claude(self):
        assert is_claude("codex") is False
        assert is_claude("codex-desktop") is False
        assert is_claude(None) is False
        assert is_claude("") is False
        assert is_claude("acme-bot") is False


# ---------------------------------------------------------------------------
# detect_entrypoint
# ---------------------------------------------------------------------------


class TestDetectEntrypointCodexAndClaude:
    """Entrypoint resolution coverage for Claude, Codex, and empty signals."""

    def test_claude_entrypoint(self):
        with mock.patch.dict(
            os.environ,
            {"CLAUDE_CODE_ENTRYPOINT": "claude-desktop"},
            clear=True,
        ):
            assert detect_entrypoint() == "claude-desktop"

    def test_codex_entrypoint_via_env_probe(self):
        # Codex sessions resolve an entrypoint via the env probe so
        # HarnessSessionStarted.envelope.context.entrypoint is populated when
        # the executor column is specific.
        with mock.patch.dict(
            os.environ,
            {
                "CODEX_THREAD_ID": "t123",
                "CODEX_INTERNAL_ORIGINATOR_OVERRIDE": "codex_cli",
            },
            clear=True,
        ):
            assert detect_entrypoint() == "codex-cli"

    def test_codex_entrypoint_uses_full_entrypoint_resolver(self):
        with mock.patch.dict(
            os.environ,
            {"CODEX_THREAD_ID": "t123"},
            clear=True,
        ):
            with mock.patch(
                "runtime.harness.codex.codex_model.resolve_entrypoint",
                return_value="codex-desktop",
            ) as resolver:
                assert detect_entrypoint() == "codex-desktop"
                resolver.assert_called_once_with()

    def test_returns_none_when_no_signal(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            assert detect_entrypoint() is None

    def test_treats_empty_string_as_unset(self):
        with mock.patch.dict(
            os.environ,
            {"CLAUDE_CODE_ENTRYPOINT": ""},
            clear=True,
        ):
            assert detect_entrypoint() is None


# ---------------------------------------------------------------------------
# canonical_harness_id
# ---------------------------------------------------------------------------


class TestCanonicalHarnessId:
    """The canonical helper maps coarse and surface-specific values to the
    ``harness_id`` enum (``claude-code`` / ``codex``) and refuses unknowns."""

    def test_codex_coarse(self):
        assert canonical_harness_id("codex") == "codex"

    def test_codex_surface_specific(self):
        assert canonical_harness_id("codex-desktop") == "codex"
        assert canonical_harness_id("codex-vscode") == "codex"
        assert canonical_harness_id("codex-cli") == "codex"
        # hypothetical future surface
        assert canonical_harness_id("codex-jetbrains") == "codex"

    def test_claude_coarse(self):
        assert canonical_harness_id("claude") == "claude-code"
        assert canonical_harness_id("claude-code") == "claude-code"

    def test_claude_surface_specific(self):
        assert canonical_harness_id("claude-desktop") == "claude-code"
        assert canonical_harness_id("claude-vscode") == "claude-code"
        assert canonical_harness_id("claude-cli") == "claude-code"
        # hypothetical future surface
        assert canonical_harness_id("claude-bedrock") == "claude-code"

    def test_whitespace_and_case_tolerated(self):
        # Live envelopes occasionally carry capitalized values from older
        # writers; the helper normalizes both.
        assert canonical_harness_id("  Codex-Desktop ") == "codex"
        assert canonical_harness_id("CLAUDE-DESKTOP") == "claude-code"

    def test_empty_and_none_refused(self):
        with pytest.raises(ValueError):
            canonical_harness_id(None)
        with pytest.raises(ValueError):
            canonical_harness_id("")
        with pytest.raises(ValueError):
            canonical_harness_id("   ")

    def test_unknown_refused(self):
        with pytest.raises(ValueError):
            canonical_harness_id("acme-bot")
        with pytest.raises(ValueError):
            canonical_harness_id("vim")
        # Bare "code" without the claude- prefix is NOT a family surface;
        # the helper must not silently treat it as Claude.
        with pytest.raises(ValueError):
            canonical_harness_id("code")


class TestComposeExecutorFromEntrypoint:
    """Regression coverage for legacy coarse aliases plus entrypoint signals."""

    def test_legacy_claude_alias_promotes_to_desktop_surface(self):
        assert (
            compose_executor_from_entrypoint("claude", "claude-desktop")
            == "claude-desktop"
        )
