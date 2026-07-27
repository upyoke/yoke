"""DB-only item-state skills must not stage or commit repository changes."""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / ".agents" / "skills" / "yoke"
DB_ONLY_STATE_SKILLS = ("block", "unblock", "freeze", "thaw")
GIT_MUTATION_PATTERNS = (
    re.compile(r"\bgit\s+(?:add|stage|commit)\b"),
    re.compile(r"\bgit\s+diff\b[^\n]*(?:--cached|--staged)\b"),
)


@pytest.mark.parametrize("skill_name", DB_ONLY_STATE_SKILLS)
def test_db_only_state_skill_does_not_stage_or_commit(skill_name: str) -> None:
    body = (SKILL_ROOT / skill_name / "SKILL.md").read_text(encoding="utf-8")

    for pattern in GIT_MUTATION_PATTERNS:
        assert pattern.search(body) is None, (
            f"{skill_name} is a DB-only state skill and must not stage or "
            f"commit repository changes: {pattern.pattern}"
        )
