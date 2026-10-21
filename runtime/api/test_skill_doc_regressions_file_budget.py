"""Machine-read names in the File Budget teaching.

- `/yoke idea` seeds the `## File Budget` section that item reads parse.
- Engineer submissions carry the `file_budget: PASS|SKIP` receipt key that
  ``yoke_core.domain.epic_submission_receipt`` parses.
"""

from __future__ import annotations

from runtime.api.skill_doc_regressions_test_helpers import (
    REPO,
    SKILLS,
    _read,
)


def test_file_budget_template_seeds_the_parsed_section() -> None:
    text = _read(SKILLS / "idea" / "file-budget.md")
    assert "## File Budget" in text


def test_submission_block_requires_file_budget_key() -> None:
    engineer = _read(REPO / "runtime" / "agents" / "engineer.md")
    assert "file_budget: PASS | SKIP" in engineer
