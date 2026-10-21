"""Onboard skill files match their install-bundle copies byte for byte."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_onboard_skills_match_installed_bytes():
    for name in ("SKILL.md", "first-work.md", "run-and-rows.md"):
        relative = Path(".agents/skills/yoke/onboard") / name
        source = (ROOT / relative).read_bytes()
        assert (
            ROOT / "packages/yoke-core/src/yoke_core/install_bundle_tree" / relative
        ).read_bytes() == source
