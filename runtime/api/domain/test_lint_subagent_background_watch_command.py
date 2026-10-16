"""The subagent-background lint must be watcher-spelling-independent.

``yoke watch pytest`` and ``python3 -m yoke_core.tools.watch_pytest`` run
the same wrapper, so backgrounding either one from a subagent turn
strands the same watcher process. The sibling module covers the module
spelling; this one covers the command spelling, plus the rendered
adapter wiring and the dogfood mode pin.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from yoke_core.domain import lint_subagent_background as lint


def _bash_payload(command: str) -> dict:
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "session_id": "sess-1",
        "agent_type": "engineer",
    }


class TestYokeWatchCommandSpelling(unittest.TestCase):
    def setUp(self):
        self._emit_patch = patch(
            "yoke_core.hooks.telemetry.emit_denial_event",
        )
        self._emit_patch.start()
        self.addCleanup(self._emit_patch.stop)
        self._mode_patch = patch.object(
            lint,
            "_read_lint_mode",
            return_value="deny",
        )
        self._mode_patch.start()
        self.addCleanup(self._mode_patch.stop)

    def test_denies_backgrounded_yoke_watch_command(self):
        verdict = lint.evaluate_payload(
            _bash_payload("yoke watch pytest -- runtime/api/ &"),
        )
        self.assertIsNotNone(verdict)
        _, reason, _, _ = verdict
        self.assertIn("yoke watch pytest", reason)

    def test_allows_foreground_yoke_watch_command(self):
        verdict = lint.evaluate_payload(
            _bash_payload("yoke watch pytest -- runtime/api/"),
        )
        self.assertIsNone(verdict)


class TestSubagentAdapterWiring(unittest.TestCase):
    """Sibling regressions on the rendered adapter files.

    Walks the on-disk Claude adapter files for every Bash-capable subagent
    and asserts one matcherless PreToolUse runner with the env-wrapped
    subagent identity. Also asserts PM/PD adapters carry zero
    ``lint_subagent_background`` invocations.
    """

    _BASH_CAPABLE_ROLES = ("engineer", "tester", "architect", "boss", "simulator")
    _NON_BASH_ROLES = ("product-manager", "product-designer")

    def _claude_adapter_path(self, role: str):
        from runtime.api.domain.test_agents_render_workspace_fixtures import (
            resolve_live_repo_root,
        )

        return (
            resolve_live_repo_root()
            / "runtime"
            / "harness"
            / "claude"
            / "agents"
            / f"yoke-{role}.md"
        )

    def test_each_bash_capable_adapter_renders_one_matcherless_pretool_entry(self):
        for role in self._BASH_CAPABLE_ROLES:
            adapter_text = self._claude_adapter_path(role).read_text(encoding="utf-8")
            expected_command = (
                f"YOKE_HOOK_AGENT_TYPE={role} yoke hook evaluate PreToolUse"
            )
            count = adapter_text.count(expected_command)
            self.assertEqual(
                count,
                1,
                f"yoke-{role}.md: expected 1 matcherless PreToolUse entry, got {count}",
            )
            # Disk-side: no --agent-type CLI flag on any PreToolUse runner.
            self.assertNotIn(
                "yoke_core.domain.lint_subagent_background --agent-type",
                adapter_text,
                f"yoke-{role}.md: stale --agent-type CLI flag still present",
            )

    def test_pm_pd_adapters_have_zero_lint_subagent_background_invocations(self):
        for role in self._NON_BASH_ROLES:
            adapter_text = self._claude_adapter_path(role).read_text(encoding="utf-8")
            self.assertNotIn(
                "lint_subagent_background",
                adapter_text,
                f"yoke-{role}.md: non-Bash agent must carry zero lint_subagent_background invocations",
            )


class TestSubagentBackgroundDeployedMode(unittest.TestCase):
    """Dogfood policy pins ``lint_subagent_background=deny``."""

    def test_dogfood_config_pins_lint_mode_to_deny(self):
        from runtime.api.domain.test_agents_render_workspace_fixtures import (
            resolve_live_repo_root,
        )

        config_path = resolve_live_repo_root() / ".yoke" / "lint-config"
        body = config_path.read_text(encoding="utf-8")
        self.assertIn(
            "lint_subagent_background=deny",
            body,
            ".yoke/lint-config must pin lint_subagent_background=deny",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
