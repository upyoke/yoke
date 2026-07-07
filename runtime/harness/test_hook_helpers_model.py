"""Model-detection tests — ``detect_model`` plus ``_extract_model_from_argv``.

Companion to ``test_hook_helpers.py``. Includes the VS Code regression
suite (covering the ``--model default`` placeholder fallthrough).
Shared fixtures live in ``conftest.py``.
"""

from __future__ import annotations

import json
import os
from unittest import mock

from runtime.harness.hook_helpers import (
    _extract_model_from_argv,
    _is_placeholder_model,
    detect_model,
)
from runtime.api.test_constants import TEST_MODEL_ID


# ---------------------------------------------------------------------------
# detect_model
# ---------------------------------------------------------------------------


class TestDetectModel:
    def test_yoke_model_env(self, no_parent_argv):
        with mock.patch.dict(os.environ, {"YOKE_MODEL": "my-model"}):
            assert detect_model() == "my-model"

    def test_codex_no_signal_is_unknown_never_fabricated(self, no_parent_argv):
        # No env, no thread id -> honest placeholder. A concrete guess
        # (the old "gpt-5.4" literal) would be laundered into rows as a
        # real detection and block the placeholder->real upgrade.
        with mock.patch.dict(os.environ, {}, clear=True):
            assert detect_model("codex") == "unknown"

    def test_codex_env_model_wins(self, no_parent_argv):
        with mock.patch.dict(os.environ, {"CODEX_MODEL": "gpt-6"}, clear=True):
            assert detect_model("codex") == "gpt-6"

    def test_codex_resolver_chain_consulted(self, no_parent_argv):
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch(
                 "runtime.harness.codex.codex_model.resolve",
                 return_value="gpt-6-real",
             ):
            assert detect_model("codex") == "gpt-6-real"

    def test_claude_default(self, no_parent_argv):
        with mock.patch.dict(os.environ, {}, clear=True):
            assert detect_model() == "unknown"

    def test_claude_default_llm_model_fallback(self, no_parent_argv):
        """Claude Desktop exposes DEFAULT_LLM_MODEL but not CLAUDE_MODEL."""
        with mock.patch.dict(
            os.environ,
            {"DEFAULT_LLM_MODEL": "claude-opus-4-7"},
            clear=True,
        ):
            assert detect_model() == "claude-opus-4-7"

    def test_claude_model_takes_precedence_over_default_llm_model(self, no_parent_argv):
        with mock.patch.dict(
            os.environ,
            {"CLAUDE_MODEL": "claude-sonnet-4-6", "DEFAULT_LLM_MODEL": "ignored"},
            clear=True,
        ):
            assert detect_model() == "claude-sonnet-4-6"

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
            assert detect_model() == "wins"

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
                "runtime.harness.hook_helpers_model._read_parent_argv",
                return_value=argv,
            ):
                assert detect_model() == "claude-opus-4-7[1m]"

    def test_parent_argv_preserves_variant_suffix(self):
        """The ``[1m]`` / ``[variant]`` suffix carries useful provenance
        (e.g. 1M-context) and must not be stripped.
        """
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch(
                "runtime.harness.hook_helpers_model._read_parent_argv",
                return_value=["claude", "--model", "claude-opus-4-7[1m]"],
            ):
                assert detect_model() == "claude-opus-4-7[1m]"

    def test_claude_model_env_wins_over_parent_argv(self):
        """Explicit env overrides still win over argv parsing."""
        with mock.patch.dict(
            os.environ, {"CLAUDE_MODEL": "env-wins"}, clear=True
        ):
            with mock.patch(
                "runtime.harness.hook_helpers_model._read_parent_argv",
                return_value=["claude", "--model", "argv-loses"],
            ):
                assert detect_model() == "env-wins"

    def test_default_llm_model_used_when_argv_has_no_model_flag(self):
        with mock.patch.dict(
            os.environ,
            {"DEFAULT_LLM_MODEL": TEST_MODEL_ID},
            clear=True,
        ):
            with mock.patch(
                "runtime.harness.hook_helpers_model._read_parent_argv",
                return_value=["claude", "--output-format", "stream-json"],
            ):
                assert detect_model() == TEST_MODEL_ID


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
        the model would mis-report every VS Code session in telemetry, so
        the parser must normalize it to empty.
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
# detect_model — VS Code regression coverage
# ---------------------------------------------------------------------------


class TestDetectModelVscodeRegression:
    """VS Code extension regression coverage (follow-up to d1f9aa51c)."""

    def test_vscode_default_argv_falls_through(self):
        """``--model default`` from the VS Code extension must not be
        returned verbatim — otherwise harness_sessions.model records
        the placeholder and every VS Code session looks identical.
        """
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch(
                "runtime.harness.hook_helpers_model._read_parent_argv",
                return_value=[
                    "/path/to/claude",
                    "--output-format",
                    "stream-json",
                    "--model",
                    "default",
                ],
            ):
                # No transcript, no env — falls all the way through to
                # "unknown" (a placeholder) so sessions_lifecycle can upgrade
                # the stored value once the transcript reveals the real model.
                assert detect_model() == "unknown"

    def test_vscode_transcript_recovers_real_model(self, tmp_path):
        """With ``--model default`` on argv and the transcript containing
        an assistant message at the canonical ``TEST_MODEL_ID``, the
        transcript wins.
        """
        transcript = tmp_path / "session.jsonl"
        transcript.write_text(
            "\n".join([
                json.dumps({"type": "user"}),
                json.dumps({"type": "assistant", "message": {"model": TEST_MODEL_ID}}),
            ]) + "\n",
            encoding="utf-8",
        )
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch(
                "runtime.harness.hook_helpers_model._read_parent_argv",
                return_value=["claude", "--model", "default"],
            ):
                assert detect_model(transcript_path=str(transcript)) == TEST_MODEL_ID

    def test_transcript_latest_wins_when_model_swapped_mid_session(self, tmp_path):
        transcript = tmp_path / "session.jsonl"
        transcript.write_text(
            "\n".join([
                json.dumps({"type": "assistant", "message": {"model": TEST_MODEL_ID}}),
                json.dumps({"type": "assistant", "message": {"model": "claude-sonnet-4-6"}}),
            ]) + "\n",
            encoding="utf-8",
        )
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch(
                "runtime.harness.hook_helpers_model._read_parent_argv",
                return_value=["claude", "--model", "default"],
            ):
                assert detect_model(transcript_path=str(transcript)) == "claude-sonnet-4-6"

    def test_transcript_skipped_when_argv_has_real_model(self, tmp_path):
        """Transcript is only a fallback — authoritative argv wins."""
        transcript = tmp_path / "session.jsonl"
        transcript.write_text(
            json.dumps({"type": "assistant", "message": {"model": TEST_MODEL_ID}}) + "\n",
            encoding="utf-8",
        )
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch(
                "runtime.harness.hook_helpers_model._read_parent_argv",
                return_value=["claude", "--model", "claude-opus-4-7[1m]"],
            ):
                assert detect_model(transcript_path=str(transcript)) == "claude-opus-4-7[1m]"

    def test_placeholder_claude_model_env_is_skipped(self, no_parent_argv):
        """Some surfaces export ``CLAUDE_MODEL=default``; don't trust it."""
        with mock.patch.dict(
            os.environ,
            {"CLAUDE_MODEL": "default", "DEFAULT_LLM_MODEL": "claude-opus-4-7"},
            clear=True,
        ):
            assert detect_model() == "claude-opus-4-7"

    def test_bracket_placeholder_claude_model_env_is_skipped(self, no_parent_argv):
        with mock.patch.dict(
            os.environ,
            {"CLAUDE_MODEL": "<synthetic>", "DEFAULT_LLM_MODEL": TEST_MODEL_ID},
            clear=True,
        ):
            assert detect_model() == TEST_MODEL_ID

    def test_placeholder_default_llm_model_env_is_skipped(self, no_parent_argv):
        with mock.patch.dict(
            os.environ,
            {"DEFAULT_LLM_MODEL": "default"},
            clear=True,
        ):
            assert detect_model() == "unknown"

    def test_transcript_placeholder_entries_are_skipped(self, tmp_path):
        transcript = tmp_path / "session.jsonl"
        transcript.write_text(
            "\n".join([
                json.dumps({"type": "assistant", "message": {"model": TEST_MODEL_ID}}),
                # A later placeholder entry must not overwrite the real one.
                json.dumps({"type": "assistant", "message": {"model": "default"}}),
                json.dumps({"type": "assistant", "message": {"model": "<synthetic>"}}),
                json.dumps({"type": "user"}),
            ]) + "\n",
            encoding="utf-8",
        )
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch(
                "runtime.harness.hook_helpers_model._read_parent_argv",
                return_value=["claude", "--model", "default"],
            ):
                assert detect_model(transcript_path=str(transcript)) == TEST_MODEL_ID

    def test_missing_transcript_path_is_safe(self, no_parent_argv):
        with mock.patch.dict(os.environ, {}, clear=True):
            assert detect_model(transcript_path="/nonexistent/transcript.jsonl") == "unknown"

    def test_malformed_transcript_lines_are_tolerated(self, tmp_path):
        transcript = tmp_path / "session.jsonl"
        transcript.write_text(
            "not json\n"
            + json.dumps({"type": "assistant", "message": {"model": TEST_MODEL_ID}}) + "\n"
            + "{not valid either\n",
            encoding="utf-8",
        )
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch(
                "runtime.harness.hook_helpers_model._read_parent_argv",
                return_value=[],
            ):
                assert detect_model(transcript_path=str(transcript)) == TEST_MODEL_ID
