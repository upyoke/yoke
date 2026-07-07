"""Doc regression guards for AGENTS.md `## Lifecycle & Routing` wording.

Sibling of `test_lifecycle_routing_docs.py`. The harness-neutral lifecycle
truth lives in AGENTS.md (`## Lifecycle & Routing` plus the discipline
sections), not in the Claude-specific `runtime/harness/claude/rules/session.md`.
This test guards that doc against drifting back to a flat
`advance -> worktree -> done` shape and ensures it explicitly names
polish/usher and the issue/epic family split.
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
    """AGENTS.md `## Lifecycle & Routing` must keep the full issue + epic flows
    visible — no collapse to `advance -> work -> done`, polish + usher named,
    shepherd + conduct named for epics."""

    @pytest.fixture
    def text(self) -> str:
        return _read(REPO / "AGENTS.md")

    @pytest.fixture
    def section_body(self, text: str) -> str:
        match = re.search(
            r"## Lifecycle & Routing\b(.*?)(?=\n## |\Z)", text, re.DOTALL
        )
        assert match, "AGENTS.md missing `## Lifecycle & Routing` section"
        return match.group(1)

    def test_no_flat_advance_to_done(self, section_body: str) -> None:
        stale = re.compile(
            r"/yoke advance YOK-N implementation.*work.*/yoke advance YOK-N done",
            re.IGNORECASE | re.DOTALL,
        )
        assert not stale.search(section_body), (
            "Lifecycle & Routing still uses the flat "
            "'/yoke advance ... → work → advance done' sequence"
        )

    def test_section_names_polish_and_usher(self, section_body: str) -> None:
        assert "/yoke polish" in section_body, (
            "Lifecycle & Routing must reference /yoke polish"
        )
        assert "/yoke usher" in section_body, (
            "Lifecycle & Routing must reference /yoke usher"
        )

    def test_section_splits_issue_and_epic_families(self, section_body: str) -> None:
        assert "Issue" in section_body and "Epic" in section_body, (
            "Lifecycle & Routing must split issue and epic command families"
        )
        assert "/yoke shepherd" in section_body
        assert "/yoke conduct" in section_body
