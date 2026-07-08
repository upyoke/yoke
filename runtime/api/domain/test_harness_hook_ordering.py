"""Tests for the universal hook-ordering module.

Asserts each event type's expected ordered chain so downstream lanes
(adapter authors, renderer) read the contract from one frozen list.
"""

from __future__ import annotations

import unittest

from yoke_contracts.hook_runner.hook_ordering import (
    HOOK_ORDERING,
    event_types,
    matchers_for,
    ordered_pipeline_for,
)

_POST_HEARTBEAT_OBSERVE = [
    "runtime.harness.hook_helpers_heartbeat",
    "yoke_core.domain.observe",
]


class TestPreToolUseBash(unittest.TestCase):
    """The PreToolUse Bash chain order is the contract every consumer reads."""

    def test_TC_bash_chain_order(self):
        chain = ordered_pipeline_for("PreToolUse", "Bash")
        # Existing entries must come first, in the documented order.
        self.assertEqual(
            chain[:5],
            [
                "yoke_core.domain.lint_db_cmd",
                "yoke_core.domain.lint_event_registry",
                "yoke_core.domain.lint_main_commit",
                "yoke_core.domain.lint_tc_label",
                "yoke_core.domain.lint_long_command_polling",
            ],
        )
        # Tail: pipe-to-truncator lint (owns the Command Output rule's
        # pipe-to-truncator clause, beside the polling lint),
        # if-status-capture lint (blocks `fi; rc=$?` masking),
        # subagent-background lint (sits next to polling lint as
        # architectural sibling), session-cwd guard, workspace-cwd-match
        # guard (writer-class cross-checkout deny), path-claim guard,
        # structured-field transform shell lint, shell-quoted function
        # payload lint, backtick-search shell footgun lint,
        # agent-CLI-contract sibling shape lints (refuse ``python3 -c
        # "from runtime..."``, ``curl localhost:8765``, and
        # ``service_client session-end`` from agent context),
        # claim-ownership mutation lint, git-stash arg-order shape lint,
        # destructive-git inspection, attestable-activity heartbeat
        # refresh, observe_pre.
        self.assertEqual(
            chain[5:],
            [
                "yoke_core.domain.lint_pipe_to_truncator",
                "yoke_core.domain.lint_if_status_capture",
                "yoke_core.domain.lint_subagent_background",
                "yoke_core.domain.lint_session_cwd",
                "yoke_core.domain.lint_workspace_cwd_match",
                "yoke_core.domain.path_claim_bash_guard",
                "yoke_core.domain.lint_structured_field_transform_shell",
                "yoke_core.domain.lint_shell_quoted_function_payload",
                "yoke_core.domain.lint_shell_backtick_search",
                "yoke_core.domain.lint_no_agent_runtime_api_import_from_c",
                "yoke_core.domain.lint_no_agent_curl_against_yoke_api",
                "yoke_core.domain.lint_no_agent_session_end",
                "yoke_core.domain.lint_claim_ownership_mutations",
                "yoke_core.domain.lint_git_stash_arg_order",
                "yoke_core.domain.lint_destructive_git",
                "runtime.harness.hook_helpers_heartbeat",
                "yoke_core.domain.observe_pre",
            ],
        )

    def test_TC_bash_chain_destructive_git_runs_before_observe_pre(self):
        """``lint_destructive_git`` runs before telemetry; the
        attestable-activity heartbeat hook sits immediately after the
        destructive lint so a refused tool call does not stamp a fresh
        heartbeat."""
        chain = ordered_pipeline_for("PreToolUse", "Bash")
        self.assertIn("yoke_core.domain.lint_destructive_git", chain)
        self.assertLess(
            chain.index(
                "yoke_core.domain.lint_structured_field_transform_shell"
            ),
            chain.index("yoke_core.domain.lint_destructive_git"),
        )
        self.assertEqual(
            chain[chain.index("yoke_core.domain.lint_destructive_git") + 1],
            "runtime.harness.hook_helpers_heartbeat",
        )
        self.assertEqual(
            chain[chain.index("runtime.harness.hook_helpers_heartbeat") + 1],
            "yoke_core.domain.observe_pre",
        )

    def test_TC_bash_chain_shell_quoted_payload_lint_position(self):
        """``lint_shell_quoted_function_payload`` runs after the structured-field
        transform lint and before the destructive-git inspector."""
        chain = ordered_pipeline_for("PreToolUse", "Bash")
        self.assertIn(
            "yoke_core.domain.lint_shell_quoted_function_payload", chain,
        )
        self.assertLess(
            chain.index(
                "yoke_core.domain.lint_structured_field_transform_shell"
            ),
            chain.index(
                "yoke_core.domain.lint_shell_quoted_function_payload"
            ),
        )
        self.assertLess(
            chain.index(
                "yoke_core.domain.lint_shell_quoted_function_payload"
            ),
            chain.index("yoke_core.domain.lint_destructive_git"),
        )

    def test_TC_bash_chain_claim_ownership_lint_between_shell_payload_and_destructive(self):
        """``lint_claim_ownership_mutations`` runs after the shell-quoted
        payload lint and before the destructive-git inspector."""
        chain = ordered_pipeline_for("PreToolUse", "Bash")
        self.assertIn(
            "yoke_core.domain.lint_claim_ownership_mutations", chain,
        )
        self.assertLess(
            chain.index(
                "yoke_core.domain.lint_shell_quoted_function_payload"
            ),
            chain.index(
                "yoke_core.domain.lint_claim_ownership_mutations"
            ),
        )
        self.assertLess(
            chain.index(
                "yoke_core.domain.lint_claim_ownership_mutations"
            ),
            chain.index("yoke_core.domain.lint_destructive_git"),
        )

    def test_TC_bash_chain_git_stash_arg_order_runs_before_destructive_git(self):
        """``lint_git_stash_arg_order`` is a cheaper shape-only denier
        than ``lint_destructive_git`` and sits immediately before it so
        misordered ``git stash push`` invocations fail fast."""
        chain = ordered_pipeline_for("PreToolUse", "Bash")
        self.assertIn(
            "yoke_core.domain.lint_git_stash_arg_order", chain,
        )
        self.assertEqual(
            chain[chain.index("yoke_core.domain.lint_git_stash_arg_order") + 1],
            "yoke_core.domain.lint_destructive_git",
        )

    def test_TC_bash_chain_session_cwd_runs_before_claim_guard(self):
        chain = ordered_pipeline_for("PreToolUse", "Bash")
        self.assertLess(
            chain.index("yoke_core.domain.lint_session_cwd"),
            chain.index("yoke_core.domain.path_claim_bash_guard"),
        )

    def test_TC_bash_chain_structured_field_transform_runs_after_path_claim(self):
        chain = ordered_pipeline_for("PreToolUse", "Bash")
        self.assertLess(
            chain.index("yoke_core.domain.path_claim_bash_guard"),
            chain.index(
                "yoke_core.domain.lint_structured_field_transform_shell"
            ),
        )
        self.assertLess(
            chain.index(
                "yoke_core.domain.lint_structured_field_transform_shell"
            ),
            chain.index("yoke_core.domain.observe_pre"),
        )

    def test_TC_bash_chain_observe_pre_is_last(self):
        chain = ordered_pipeline_for("PreToolUse", "Bash")
        self.assertEqual(chain[-1], "yoke_core.domain.observe_pre")


class TestPreToolUseSubagentLint(unittest.TestCase):
    """AC-10: ``lint_subagent_background`` is registered in the protected chains."""

    def test_TC_subagent_lint_in_bash_chain_after_polling(self):
        chain = ordered_pipeline_for("PreToolUse", "Bash")
        self.assertIn("yoke_core.domain.lint_subagent_background", chain)
        self.assertLess(
            chain.index("yoke_core.domain.lint_long_command_polling"),
            chain.index("yoke_core.domain.lint_subagent_background"),
        )
        self.assertLess(
            chain.index("yoke_core.domain.lint_if_status_capture"),
            chain.index("yoke_core.domain.lint_subagent_background"),
        )

    def test_TC_subagent_lint_in_monitor_chain(self):
        chain = ordered_pipeline_for("PreToolUse", "Monitor")
        self.assertIn("yoke_core.domain.lint_subagent_background", chain)
        # Monitor chain has the hint_monitor_relay tail; the subagent
        # lint must come BEFORE that hint so a deny short-circuits the
        # relay reminder.
        self.assertLess(
            chain.index("yoke_core.domain.lint_subagent_background"),
            chain.index("yoke_core.domain.hint_monitor_relay"),
        )
        self.assertEqual(chain[-1], "yoke_core.domain.observe_pre")

    def test_TC_subagent_lint_in_schedule_wakeup_chain(self):
        chain = ordered_pipeline_for("PreToolUse", "ScheduleWakeup")
        self.assertEqual(
            chain,
            [
                "yoke_core.domain.lint_subagent_background",
                "yoke_core.domain.observe_pre",
            ],
        )


class TestPreToolUseEditWrite(unittest.TestCase):
    """Edit and Write chains both gate on cwd then path-claim before file lints."""

    def test_TC_edit_chain_starts_with_cwd_and_claim_guard(self):
        chain = ordered_pipeline_for("PreToolUse", "Edit")
        self.assertEqual(chain[0], "yoke_core.domain.lint_session_cwd")
        self.assertEqual(chain[1], "yoke_core.domain.path_claim_pre_edit_guard")

    def test_TC_edit_chain_observe_pre_is_last(self):
        chain = ordered_pipeline_for("PreToolUse", "Edit")
        self.assertEqual(chain[-1], "yoke_core.domain.observe_pre")

    def test_TC_write_chain_starts_with_cwd_and_claim_guard(self):
        chain = ordered_pipeline_for("PreToolUse", "Write")
        self.assertEqual(chain[0], "yoke_core.domain.lint_session_cwd")
        self.assertEqual(chain[1], "yoke_core.domain.path_claim_pre_edit_guard")

    def test_TC_write_chain_observe_pre_is_last(self):
        chain = ordered_pipeline_for("PreToolUse", "Write")
        self.assertEqual(chain[-1], "yoke_core.domain.observe_pre")

    def test_TC_write_chain_includes_file_lints_after_guard(self):
        chain = ordered_pipeline_for("PreToolUse", "Write")
        # ``lint_write_path`` is a file-shape lint; it follows the guards.
        self.assertIn("yoke_core.domain.lint_write_path", chain)
        self.assertLess(
            chain.index("yoke_core.domain.path_claim_pre_edit_guard"),
            chain.index("yoke_core.domain.lint_write_path"),
        )

    def test_TC_apply_patch_chain_matches_edit_shape(self):
        # Codex apply_patch is treated as a multi-file write; same gate ordering.
        chain = ordered_pipeline_for("PreToolUse", "apply_patch")
        self.assertEqual(chain[0], "yoke_core.domain.lint_session_cwd")
        self.assertEqual(chain[1], "yoke_core.domain.path_claim_pre_edit_guard")
        self.assertEqual(chain[-1], "yoke_core.domain.observe_pre")


class TestNonPreEvents(unittest.TestCase):
    """PostToolUse, SessionStart/End, UserPromptSubmit, Stop chains."""

    def test_TC_post_tool_use_bash_includes_db_error_hook(self):
        chain = ordered_pipeline_for("PostToolUse", "Bash")
        self.assertEqual(chain[0], "yoke_core.domain.db_error_hook")
        self.assertEqual(chain[-1], "yoke_core.domain.observe")

    def test_TC_post_tool_use_bash_includes_field_note_hint(self):
        # PostToolUse field-note hint registered between the
        # DB-error advisory (front-door first) and telemetry (tail).
        chain = ordered_pipeline_for("PostToolUse", "Bash")
        self.assertIn(
            "yoke_core.domain.hint_posttool_field_note", chain,
        )
        self.assertLess(
            chain.index("yoke_core.domain.db_error_hook"),
            chain.index("yoke_core.domain.hint_posttool_field_note"),
        )
        self.assertLess(
            chain.index("yoke_core.domain.hint_posttool_field_note"),
            chain.index("yoke_core.domain.observe"),
        )

    def test_TC_post_tool_use_default_just_observe(self):
        chain = ordered_pipeline_for("PostToolUse", "Edit")
        # Falls back to _default chain when matcher not registered.
        self.assertEqual(chain, _POST_HEARTBEAT_OBSERVE)

    def test_TC_post_tool_use_failure_observe(self):
        chain = ordered_pipeline_for("PostToolUseFailure")
        self.assertEqual(chain, _POST_HEARTBEAT_OBSERVE)

    def test_TC_session_start_runs_session_hooks(self):
        chain = ordered_pipeline_for("SessionStart")
        self.assertEqual(chain, ["runtime.harness.hook_runner.session_dispatch"])

    def test_TC_session_end_runs_session_hooks(self):
        chain = ordered_pipeline_for("SessionEnd")
        self.assertEqual(chain, ["runtime.harness.hook_runner.session_dispatch"])

    def test_TC_user_prompt_submit_runs_session_hooks(self):
        chain = ordered_pipeline_for("UserPromptSubmit")
        self.assertEqual(chain, ["runtime.harness.hook_runner.session_dispatch"])

    def test_TC_stop_runs_session_hooks(self):
        chain = ordered_pipeline_for("Stop")
        self.assertEqual(chain, ["runtime.harness.hook_runner.session_dispatch"])


class TestRegistryShape(unittest.TestCase):
    """Top-level shape contracts: frozen view, fresh-list returns, etc."""

    def test_TC_event_types_includes_required(self):
        types = event_types()
        for required in (
            "PreToolUse",
            "PostToolUse",
            "PermissionRequest",
            "SessionStart",
            "UserPromptSubmit",
            "Stop",
        ):
            self.assertIn(required, types)

    def test_TC_unknown_event_returns_empty_list(self):
        self.assertEqual(ordered_pipeline_for("DoesNotExist"), [])

    def test_TC_unknown_matcher_falls_back_to_default(self):
        chain = ordered_pipeline_for("PostToolUse", "TotallyMadeUp")
        self.assertEqual(chain, _POST_HEARTBEAT_OBSERVE)

    def test_TC_pretooluse_unknown_matcher_returns_empty_when_no_default(self):
        # PreToolUse intentionally has no _default — every matcher is
        # explicit. An unknown matcher should produce an empty list.
        chain = ordered_pipeline_for("PreToolUse", "TotallyMadeUp")
        self.assertEqual(chain, [])

    def test_TC_returned_list_is_fresh(self):
        chain1 = ordered_pipeline_for("PreToolUse", "Bash")
        chain2 = ordered_pipeline_for("PreToolUse", "Bash")
        chain1.append("mutated")
        self.assertNotIn("mutated", chain2)

    def test_TC_matchers_for_pretooluse_lists_all(self):
        matchers = matchers_for("PreToolUse")
        for required in ("Bash", "Edit", "Write", "Read", "Monitor"):
            self.assertIn(required, matchers)

    def test_TC_matchers_for_unknown_returns_empty(self):
        self.assertEqual(matchers_for("DoesNotExist"), [])

    def test_TC_hook_ordering_view_is_read_only(self):
        # MappingProxyType raises TypeError on assignment.
        with self.assertRaises(TypeError):
            HOOK_ORDERING["PreToolUse"]["Bash"] = ()  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()
