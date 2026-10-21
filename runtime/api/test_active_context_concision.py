"""Active plans, progress, handoffs, and resume notes stay current-state."""

from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_AGENTS = _REPO / "runtime" / "agents"
_STEER = _REPO / ".agents" / "skills" / "yoke" / "steer"


def _read(relative: str) -> str:
    return (_REPO / relative).read_text(encoding="utf-8")


def _command(skill: str) -> str:
    """One `/yoke` command's entrypoint plus its phase references.

    A command routes from a short SKILL.md into per-phase files, so a rule it
    teaches lives in whichever phase governs it. These assertions care that
    the command teaches it, not which file holds it.
    """
    root = _REPO / ".agents" / "skills" / "yoke" / skill
    entry = root / "SKILL.md"
    phases = sorted(p for p in root.glob("*.md") if p.name != "SKILL.md")
    return "\n".join(p.read_text(encoding="utf-8") for p in (entry, *phases))


def _words(text: str) -> str:
    return " ".join(text.split())


class TestCurrentStateCheckpointTeaching:
    def test_prompt_philosophy_names_checkpoint_fields_not_essays(self):
        text = _words(_read("docs/prompt-philosophy.md"))
        assert "current-state checkpoints" in text
        for field in (
            "objective",
            "standing decisions/holds",
            "active work",
            "blockers",
            "next actions",
            "links to durable evidence",
        ):
            assert field in text
        assert "accumulated essays" in text
        assert "make this artifact cold-start complete" not in text

    def test_wrapup_progress_log_is_a_checkpoint_template(self):
        text = _command("wrapup")
        assert '--headline "Session checkpoint"' in text
        assert "{objective, blockers, next action, evidence}" in text
        assert "cold-start complete" not in text

    def test_steer_live_status_heading(self):
        assert (
            "## Live status — steering snapshot "
            "(refresh or replace on next steering handoff)"
        ) in _read(".agents/skills/yoke/steer/loop.md")

    def test_progress_log_deep_home_is_a_checkpoint(self):
        text = _words(_read("docs/public/agents/rules/item-writes.md"))
        assert "current-state checkpoint" in text
        assert "Do not restate full results" in text
        assert "historical status snapshots" in text

    def test_session_continuity_rule_is_a_checkpoint(self):
        text = _words(_read("AGENTS.md"))
        assert "reload the current-phase skill" in text
        home = _words(_read("docs/public/agents/rules/item-writes.md"))
        assert "Each entry is a current-state checkpoint" in home
        assert "dead ends, gotchas" not in text

    def test_canonical_agent_bodies_drop_cold_start_complete(self):
        leftover = []
        for path in sorted(_AGENTS.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            if "cold-start complete" in text or "cold-start-complete" in text:
                leftover.append(path.name)
        assert leftover == []


class TestSteerStrategyReadCommands:
    def test_skill_and_loop_use_doc_get(self):
        skill = _command("steer")
        assert "yoke strategy doc get {SLUG}" in skill
        assert "yoke strategy doc get {SLUG}" in _read(
            ".agents/skills/yoke/steer/loop.md"
        )
