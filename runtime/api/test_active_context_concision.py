"""Steer's Live status section and strategy read commands stay addressable."""

from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (_REPO / relative).read_text(encoding="utf-8")


def _command(skill: str) -> str:
    """One `/yoke` command's entrypoint plus its phase references."""
    root = _REPO / ".agents" / "skills" / "yoke" / skill
    entry = root / "SKILL.md"
    phases = sorted(p for p in root.glob("*.md") if p.name != "SKILL.md")
    return "\n".join(p.read_text(encoding="utf-8") for p in (entry, *phases))


def test_steer_live_status_heading():
    # `yoke strategy doc section replace` addresses this section by heading.
    assert (
        "## Live status — steering snapshot "
        "(refresh or replace on next steering handoff)"
    ) in _read(".agents/skills/yoke/steer/loop.md")


def test_skill_and_loop_use_doc_get():
    assert "yoke strategy doc get {SLUG}" in _command("steer")
    assert "yoke strategy doc get {SLUG}" in _read(".agents/skills/yoke/steer/loop.md")
