"""Structure checks for the harness-side /yoke onboard adoption skill."""

from __future__ import annotations

import re

from runtime.api.skill_doc_regressions_test_helpers import SKILLS, _read


ONBOARD_DIR = SKILLS / "onboard"
ONBOARD = ONBOARD_DIR / "SKILL.md"


def test_onboard_skill_exists_with_expected_frontmatter():
    text = _read(ONBOARD)
    assert "name: onboard" in text


def test_onboard_router_reaches_every_step_file():
    """Every onboard step file is linked from the router or a linked step."""
    linked = set()
    for path in ONBOARD_DIR.glob("*.md"):
        linked.update(re.findall(r"\]\(([\w-]+\.md)\)", _read(path)))
    router_links = set(re.findall(r"\]\(([\w-]+\.md)\)", _read(ONBOARD)))
    assert "run-and-rows.md" in router_links
    for path in ONBOARD_DIR.glob("*.md"):
        if path.name != "SKILL.md":
            assert path.name in linked, f"{path.name} is unreachable from onboard"
