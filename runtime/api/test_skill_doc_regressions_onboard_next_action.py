"""Onboard teaching consumes the shared next-action projection."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_onboard_skills_teach_next_action_and_keep_installed_bytes():
    for name in ("SKILL.md", "first-work.md", "run-and-rows.md"):
        relative = Path(".agents/skills/yoke/onboard") / name
        source = (ROOT / relative).read_bytes()
        assert b"run.next_action" in source
        assert b"setup_readiness.unmet_rows" not in source
        assert (
            ROOT / "packages/yoke-core/src/yoke_core/install_bundle_tree" / relative
        ).read_bytes() == source
