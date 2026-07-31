"""The subagent-background lint must be watcher-spelling-independent.

``yoke watch pytest`` and ``python3 -m yoke_core.tools.watch_pytest`` run
the same wrapper, so backgrounding either one from a subagent turn
strands the same watcher process. The sibling module covers the module
spelling; this one covers the command spelling.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from yoke_core.domain import lint_subagent_background as lint


def _bash_payload(command: str) -> dict:
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "session_id": "sess-1",
    }


class TestYokeWatchCommandSpelling(unittest.TestCase):
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


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
