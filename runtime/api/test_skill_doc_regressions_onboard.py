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


def test_verification_binding_probes_quick_argv_on_local_hosts():
    """Without CI the suite runs here, so onboarding runs the argv before binding."""
    text = " ".join(_read(ONBOARD_DIR / "verification-binding.md").split())
    probe = text.index("Run `{quick_argv}` once")
    assert "No `ci_workflow_file`" in text
    assert probe < text.index("yoke qa registered-command set")
    assert "uv run --with pytest" in text
    assert "No tests collected passes" in text
    assert "`argv verification`" in text and "probe result" in text
