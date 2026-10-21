"""Doc regressions for the engineer agent submission-checks receipt.

Pins the receipt markers and fields that the submission receipt parser reads.
"""

from __future__ import annotations

from runtime.api.skill_doc_regressions_test_helpers import AGENTS, _read


ENGINEER = AGENTS / "yoke-engineer.md"


class TestEngineerSubmissionGate:
    """The engineer agent teaches the parsed submission-checks block."""

    def test_engineer_defines_submission_checks_block(self):
        assert "---SUBMISSION-CHECKS-START---" in _read(ENGINEER)

    def test_engineer_teaches_clean_worktree_field(self):
        assert "clean_worktree:" in _read(ENGINEER)
