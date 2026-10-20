"""Doc regressions: conduct entry activation acquires the item work claim.

Verifies that entry-activation.md teaches the registered work-claim adapter,
leaves session presence to the harness hooks, and never reads claim state
through a raw database path or worktree path.
"""

from __future__ import annotations

import unittest

from runtime.api.skill_doc_regressions_test_helpers import SKILLS, _read


def _read_entry_activation() -> str:
    return _read(SKILLS / "conduct" / "entry-activation.md")


class TestEntryActivationTeachesFunctionCallAdapters(unittest.TestCase):
    def setUp(self) -> None:
        self.text = _read_entry_activation()

    def test_teaches_claim_work_adapter(self) -> None:
        self.assertIn("yoke claims work acquire --item PREFIX-N", self.text)

    def test_does_not_teach_explicit_session_touch(self) -> None:
        """Session presence is auto-handled by the harness session hooks."""
        self.assertNotIn("session-touch", self.text)

    def test_never_reads_claim_state_through_raw_paths(self) -> None:
        for forbidden in ("db_router", "yoke.db", ".worktrees/", ">/dev/null 2>&1"):
            self.assertNotIn(forbidden, self.text)


if __name__ == "__main__":
    unittest.main()
