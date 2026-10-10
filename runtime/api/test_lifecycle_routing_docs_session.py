"""Regression guards for AGENTS.md workflow-version routing doctrine.

AGENTS.md binds the operation home before acting; that home owns exact
workflow-version routing. These checks preserve both the loading directive
and the pin contract without duplicating the operation recipe in startup.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise RuntimeError("Unable to locate repo root from test module location.")


REPO = _repo_root()


def _read(path: Path) -> str:
    assert path.is_file(), f"expected file to exist: {path}"
    return path.read_text(encoding="utf-8")


class TestLifecycleRoutingSection:
    """AGENTS.md must route through the item's immutable workflow pin."""

    @pytest.fixture
    def text(self) -> str:
        return _read(REPO / "AGENTS.md")

    @pytest.fixture
    def section_body(self, text: str) -> str:
        assert (
            "Read the applicable `.yoke/docs/reference/agent-rules/` home first" in text
        )
        assert "`lanes-and-claims.md`" in text
        assert "live pinned workflow's half-open binding" in text
        home = _read(REPO / ".yoke/docs/reference/agent-rules/lanes-and-claims.md")
        match = re.search(
            r"## Lifecycle and routing\b(.*?)(?=\n## |\Z)", home, re.DOTALL
        )
        assert match, "operation home missing lifecycle routing contract"
        return match.group(1)

    def test_no_flat_advance_to_done(self, section_body: str) -> None:
        stale = re.compile(
            r"/yoke "
            + "advance PREFIX-N implementation.*work.*/yoke "
            + "advance PREFIX-N done",
            re.IGNORECASE | re.DOTALL,
        )
        assert not stale.search(section_body), (
            "Lifecycle & Routing still uses the flat "
            "retired implementation-to-done sequence"
        )

    def test_section_names_immutable_pin_and_exact_version(
        self, section_body: str
    ) -> None:
        assert "`workflow_id` / `workflow_version_id`" in section_body
        assert "yoke workflows item get PREFIX-N" in section_body
        assert "yoke workflows version get WORKFLOW VERSION" in section_body

    def test_section_routes_by_skill_binding(self, section_body: str) -> None:
        assert "half-open interval" in section_body
        assert "/yoke <skill_id>" in section_body
        assert "`through_stage_id`" in section_body

    def test_section_uses_policies_not_item_type(self, section_body: str) -> None:
        assert "`policies.worktrees`" in section_body
        assert "`policies.generated_children`" in section_body
        assert "not from a workflow-id branch" in section_body
        assert "Issue command family" not in section_body
        assert "Epic command family" not in section_body
