"""Active plans, progress, handoffs, and resume notes stay current-state."""

from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_AGENTS = _REPO / "runtime" / "agents"
_STEER = _REPO / ".agents" / "skills" / "yoke" / "steer"


def _read(relative: str) -> str:
    return (_REPO / relative).read_text(encoding="utf-8")


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
        text = _read(".agents/skills/yoke/wrapup/SKILL.md")
        assert "current-state checkpoint" in text
        assert "--headline \"Session checkpoint\"" in text
        assert "Objective:" in text
        assert "Standing decisions/holds:" in text
        assert "Active work:" in text
        assert "Blockers:" in text
        assert "Next action:" in text
        assert "Evidence:" in text
        assert "cold-start complete" not in text

    def test_steer_loop_reloads_phase_after_compaction(self):
        loop = _words(_read(".agents/skills/yoke/steer/loop.md"))
        assert "After compaction or resume, reload this phase" in loop
        assert "reattach the running watcher or re-arm it when absent" in loop
        assert "discarded context is gone" in loop
        assert "Preserve unresolved holds and obligations from other" in loop
        assert "Dated status sections other than this one are stale" not in loop
        assert (
            "## Live status — steering snapshot "
            "(refresh or replace on next steering handoff)"
        ) in _read(".agents/skills/yoke/steer/loop.md")

    def test_steer_extracts_current_state_without_copying_history(self):
        skill = _words(_read(".agents/skills/yoke/steer/SKILL.md"))
        assert "cold-start refresh" in skill
        assert "do not copy historical status sections" in skill.lower()

    def test_progress_log_deep_home_is_a_checkpoint(self):
        text = _words(
            _read("docs/public/reference/agent-rules/item-writes.md")
        )
        assert "current-state checkpoint" in text
        assert "Do not restate full results" in text
        assert "historical status snapshots" in text

    def test_session_continuity_rule_is_a_checkpoint(self):
        text = _words(_read("AGENTS.md"))
        assert "Progress Log entries are current-state checkpoints" in text
        assert "reload the current-phase skill" in text
        assert "dead ends, gotchas" not in text

    def test_canonical_agent_bodies_drop_cold_start_complete(self):
        leftover = []
        for path in sorted(_AGENTS.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            if "cold-start complete" in text or "cold-start-complete" in text:
                leftover.append(path.name)
        assert leftover == []


class TestSteerCorpusKeepsRequiredRefreshVocabulary:
    def test_skill_still_extracts_open_work_index(self):
        skill = _read(".agents/skills/yoke/steer/SKILL.md")
        assert "In flight" in skill
        assert "Ready to staff" in skill
        assert "Blocked" in skill
        assert "Awaiting operator decision" in skill
        assert "yoke strategy doc get {SLUG}" in skill
        assert "yoke strategy doc get {SLUG}" in _read(
            ".agents/skills/yoke/steer/loop.md"
        )
