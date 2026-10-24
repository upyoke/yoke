"""Shared QA teaching ships to every project, so it carries no Yoke-only steps."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
BUNDLE = "packages/yoke-core/src/yoke_core/install_bundle_tree"
SHARED_QA_TEACHING = [
    "runtime/agents/qa-walker.md",
    "runtime/harness/claude/agents/yoke-qa-walker.md",
    "runtime/harness/codex/agents/yoke-qa-walker.toml",
    "runtime/harness/cursor/agents/yoke-qa-walker.md",
    "docs/public/verification/exploration.md",
    "docs/public/verification/exploration-evidence.md",
    f"{BUNDLE}/runtime/harness/claude/agents/yoke-qa-walker.md",
    f"{BUNDLE}/runtime/harness/codex/agents/yoke-qa-walker.toml",
    f"{BUNDLE}/runtime/harness/cursor/agents/yoke-qa-walker.md",
    f"{BUNDLE}/docs/public/verification/exploration.md",
    f"{BUNDLE}/docs/public/verification/exploration-evidence.md",
]
YOKE_ONLY = re.compile(
    r"connected-machine|connected_machine|fixture_project|dispose_projects"
    r"|yoke-qa-\S*-source"
)


@pytest.mark.parametrize("path", SHARED_QA_TEACHING)
def test_shared_qa_teaching_names_no_yoke_only_cleanup(path: str) -> None:
    text = (ROOT / path).read_text(encoding="utf-8")
    assert YOKE_ONLY.findall(text) == []
    assert "product's own commands" in text
