"""Requested-model detection — ``detect_requested_model`` plus argv parsing.

Companion to ``test_hook_helpers.py``. Every source here is request-side:
what the session was *asked* to run. What a provider actually served is a
different fact read from the harness's own artifact, and its coverage lives
in ``test_model_attestation.py``.

Includes the VS Code regression suite (the ``--model default`` placeholder
fallthrough). Shared fixtures live in ``conftest.py``.
"""

from __future__ import annotations

import os
from unittest import mock

from yoke_core.hooks.helpers import (
    _extract_model_from_argv,
    _is_placeholder_model,
    detect_requested_model,
)
from runtime.api.test_constants import TEST_MODEL_ID


# ---------------------------------------------------------------------------
# detect_requested_model
# ---------------------------------------------------------------------------


class TestDetectRequestedModel:
    def test_yoke_model_env(self, no_parent_argv):
        with mock.patch.dict(os.environ, {"YOKE_MODEL": "my-model"}):
            assert detect_requested_model() == "my-model"

    def test_codex_no_signal_is_unknown_never_fabricated(self, no_parent_argv):
        # No env -> honest placeholder. A concrete guess (the old "gpt-5.4"
        # literal) would be laundered into rows as a real request.
        with mock.patch.dict(os.environ, {}, clear=True):
            assert detect_requested_model("codex") == "unknown"

    def test_codex_env_model_wins(self, no_parent_argv):
        with mock.patch.dict(os.environ, {"CODEX_MODEL": "gpt-6"}, clear=True):
            assert detect_requested_model("codex") == "gpt-6"

    def test_claude_default(self, no_parent_argv):
        with mock.patch.dict(os.environ, {}, clear=True):
            assert detect_requested_model() == "unknown"

    def test_claude_default_llm_model_fallback(self, no_parent_argv):
        """Claude Desktop exposes DEFAULT_LLM_MODEL but not CLAUDE_MODEL."""
        with mock.patch.dict(
            os.environ,
            {"DEFAULT_LLM_MODEL": "claude-opus-4-7"},
            clear=True,
        ):
            assert detect_requested_model() == "claude-opus-4-7"

    def test_claude_model_takes_precedence_over_default_llm_model(self, no_parent_argv):
        with mock.patch.dict(
            os.environ,
            {"CLAUDE_MODEL": "claude-sonnet-4-6", "DEFAULT_LLM_MODEL": "ignored"},
            clear=True,
        ):
            assert detect_requested_model() == "claude-sonnet-4-6"

    def test_yoke_model_overrides_everything(self, no_parent_argv):
        with mock.patch.dict(
            os.environ,
            {
                "YOKE_MODEL": "wins",
                "CLAUDE_MODEL": "loses",
                "DEFAULT_LLM_MODEL": "loses",
            },
            clear=True,
        ):
            assert detect_requested_model() == "wins"

    def test_parent_argv_wins_over_default_llm_model(self):
        """Claude Desktop's stale DEFAULT_LLM_MODEL must not win over the
        actual --model the CLI was invoked with.
        """
        argv = [
            "/path/to/claude",
            "--output-format",
            "stream-json",
            "--model",
            "claude-opus-4-7[1m]",
            "--permission-mode",
            "acceptEdits",
        ]
        with mock.patch.dict(
            os.environ,
            {"DEFAULT_LLM_MODEL": TEST_MODEL_ID},
            clear=True,
        ):
            with mock.patch(
                "yoke_core.hooks.helpers_model._read_parent_argv",
                return_value=argv,
            ):
                assert detect_requested_model() == "claude-opus-4-7[1m]"

    def test_parent_argv_preserves_variant_suffix(self):
        """The ``[1m]`` suffix IS the context-tier request and must survive.

        Nothing downstream can recover the ask once the suffix is stripped:
        no provider response ever returns it.
        """
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch(
                "yoke_core.hooks.helpers_model._read_parent_argv",
                return_value=["claude", "--model", "claude-opus-4-7[1m]"],
            ):
                assert detect_requested_model() == "claude-opus-4-7[1m]"

    def test_claude_model_env_wins_over_parent_argv(self):
        """Explicit env overrides still win over argv parsing."""
        with mock.patch.dict(
            os.environ, {"CLAUDE_MODEL": "env-wins"}, clear=True
        ):
            with mock.patch(
                "yoke_core.hooks.helpers_model._read_parent_argv",
                return_value=["claude", "--model", "argv-loses"],
            ):
                assert detect_requested_model() == "env-wins"

    def test_default_llm_model_used_when_argv_has_no_model_flag(self):
        with mock.patch.dict(
            os.environ,
            {"DEFAULT_LLM_MODEL": TEST_MODEL_ID},
            clear=True,
        ):
            with mock.patch(
                "yoke_core.hooks.helpers_model._read_parent_argv",
                return_value=["claude", "--output-format", "stream-json"],
            ):
                assert detect_requested_model() == TEST_MODEL_ID


# ---------------------------------------------------------------------------
# _extract_model_from_argv
# ---------------------------------------------------------------------------


class TestExtractModelFromArgv:
    def test_space_separated_flag(self):
        assert _extract_model_from_argv(
            ["claude", "--model", "claude-opus-4-7", "--verbose"]
        ) == "claude-opus-4-7"

    def test_equals_form(self):
        assert _extract_model_from_argv(
            ["claude", "--model=claude-sonnet-4-6"]
        ) == "claude-sonnet-4-6"

    def test_preserves_variant_suffix(self):
        assert _extract_model_from_argv(
            ["claude", "--model", "claude-opus-4-7[1m]"]
        ) == "claude-opus-4-7[1m]"

    def test_empty_argv(self):
        assert _extract_model_from_argv([]) == ""

    def test_no_model_flag(self):
        assert _extract_model_from_argv(
            ["claude", "--verbose", "--output-format", "stream-json"]
        ) == ""

    def test_model_flag_without_value_at_end(self):
        # ``--model`` as the last token with no following value — don't crash
        assert _extract_model_from_argv(["claude", "--model"]) == ""

    def test_default_placeholder_is_treated_as_unset(self):
        """The VS Code extension launches with ``--model default`` to mean
        "use the user-selected default". Recording that literal string as
        the request would mis-report every VS Code session, so the parser
        must normalize it to empty.
        """
        assert _extract_model_from_argv(
            ["claude", "--model", "default", "--verbose"]
        ) == ""

    def test_default_placeholder_equals_form(self):
        assert _extract_model_from_argv(["claude", "--model=default"]) == ""

    def test_placeholder_is_case_insensitive(self):
        assert _extract_model_from_argv(["claude", "--model", "Default"]) == ""
        assert _extract_model_from_argv(["claude", "--model", "AUTO"]) == ""

    def test_bracket_placeholder_is_treated_as_unset(self):
        assert _is_placeholder_model("<synthetic>") is True
        assert _extract_model_from_argv(["claude", "--model", "<synthetic>"]) == ""


# ---------------------------------------------------------------------------
# detect_requested_model — VS Code regression coverage
# ---------------------------------------------------------------------------


class TestDetectRequestedModelVscodeRegression:
    """VS Code extension regression coverage (follow-up to d1f9aa51c)."""

    def test_vscode_default_argv_falls_through(self):
        """``--model default`` from the VS Code extension must not be
        returned verbatim — otherwise every VS Code session records the
        placeholder as its request and they all look identical.
        """
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch(
                "yoke_core.hooks.helpers_model._read_parent_argv",
                return_value=[
                    "/path/to/claude",
                    "--output-format",
                    "stream-json",
                    "--model",
                    "default",
                ],
            ):
                # No env, no usable argv — falls through to the placeholder.
                # The session's real model arrives on the served side, from
                # the transcript, once the first turn completes.
                assert detect_requested_model() == "unknown"

    def test_placeholder_claude_model_env_is_skipped(self, no_parent_argv):
        """Some surfaces export ``CLAUDE_MODEL=default``; don't trust it."""
        with mock.patch.dict(
            os.environ,
            {"CLAUDE_MODEL": "default", "DEFAULT_LLM_MODEL": "claude-opus-4-7"},
            clear=True,
        ):
            assert detect_requested_model() == "claude-opus-4-7"

    def test_bracket_placeholder_claude_model_env_is_skipped(self, no_parent_argv):
        with mock.patch.dict(
            os.environ,
            {"CLAUDE_MODEL": "<synthetic>", "DEFAULT_LLM_MODEL": TEST_MODEL_ID},
            clear=True,
        ):
            assert detect_requested_model() == TEST_MODEL_ID

    def test_placeholder_default_llm_model_env_is_skipped(self, no_parent_argv):
        with mock.patch.dict(
            os.environ,
            {"DEFAULT_LLM_MODEL": "default"},
            clear=True,
        ):
            assert detect_requested_model() == "unknown"
