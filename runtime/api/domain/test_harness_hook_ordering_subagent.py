"""Tests for the subagent-background hook placement."""

from __future__ import annotations

import unittest

from yoke_contracts.hook_runner.hook_ordering import ordered_pipeline_for


class TestPreToolUseSubagentLint(unittest.TestCase):
    """``lint_subagent_background`` is registered in protected chains."""

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
                "yoke_core.hooks.session_message_delivery",
                "yoke_core.hooks.session_launch_attestation",
                "yoke_core.domain.observe_pre",
            ],
        )
