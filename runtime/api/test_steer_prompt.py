"""Static regression coverage for the /yoke steer prompt surface."""

from __future__ import annotations

from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_STEER_DIR = _REPO_ROOT / ".agents" / "skills" / "yoke" / "steer"


def _read(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if path.name == "loop.md":
        text += _read(_STEER_DIR / "watching.md") + _read(
            _STEER_DIR / "fleet-findings.md"
        )
    return text


def _words(text: str) -> str:
    """Normalize whitespace in command examples."""
    return " ".join(text.split())


def _corpus() -> str:
    return "".join(_read(path) for path in sorted(_STEER_DIR.glob("*.md")))


class TestSteerSkillContract:
    def test_skill_id_is_steer_not_coordinate(self):
        text = _read(_STEER_DIR / "SKILL.md")
        assert text.startswith("---")
        assert "name: steer" in text.split("---", 2)[1]
        assert "# /yoke steer" in text

    def test_strategy_doc_commands_and_required_headings(self):
        text = _corpus()
        assert "STRATEGY-DOC-SLUG" in text
        assert "yoke strategy doc create" in text
        assert "# Objective" in text
        assert "# Frontier" in text
        assert "# Decisions" in text
        assert "# Gates" in text
        assert "--doc" in text
        assert "--plan-doc" in text
        assert "yoke strategy doc-claim acquire" not in text

    def test_plan_claim_command(self):
        skill = _words(_corpus())
        assert (
            "yoke claims steering acquire --project {_project} --plan-doc {SLUG}"
        ) in skill

    def test_vocabulary_is_steering_not_coordination(self):
        corpus = _corpus()
        assert "yoke claims steering acquire" in corpus
        assert "coordination-scope" not in corpus
        assert "coordination_scope" not in corpus

    def test_feed_command_reference(self):
        assert "`/yoke feed`" in _corpus()

    def test_loop_command_and_phase_references(self):
        loop = _read(_STEER_DIR / "loop.md")
        blitz_handoff = _read(_STEER_DIR / "blitz-handoff.md")
        assert "blitz-handoff.md" in _read(_STEER_DIR / "SKILL.md")
        assert "yoke charge schedule" in loop
        assert "yoke say --item PREFIX-N --stdin" in loop
        assert "yoke messages acknowledge" in loop
        assert "yoke strategy doc get" in loop
        assert "yoke strategy execution link" in blitz_handoff
        assert "yoke claims steering release" in blitz_handoff
        assert "yoke steering report get" in loop

    def test_each_pass_reads_plan_and_report_before_messages(self):
        loop = _read(_STEER_DIR / "loop.md")
        assert loop.index("yoke strategy doc get {SLUG}") < loop.index(
            "yoke charge schedule"
        )
        assert loop.index("yoke steering report get") < loop.index("yoke messages list")

    def test_report_command_replaces_direct_queries(self):
        raw = _read(_STEER_DIR / "loop.md")
        loop = _words(raw)
        assert "yoke steering report get" in loop
        assert "`native_process_gone`" in loop
        assert "FROM session_message_recipients r JOIN harness_sessions" not in raw
        assert "FROM work_claims c JOIN harness_sessions s" not in raw
        assert "FROM session_messages m JOIN session_message_recipients r" not in raw
        assert "FROM items i LEFT JOIN work_claims c" not in raw
        assert "FROM session_launches" not in raw

    def test_hold_and_cancel_commands(self):
        loop = _words(_read(_STEER_DIR / "loop.md"))
        assert "yoke items freeze PREFIX-N" in loop
        assert "yoke items cancel PREFIX-N --reason TEXT" in loop

    def test_retired_liveness_query_absent(self):
        corpus = _corpus()
        assert "liveness=stale" not in corpus

    def test_blitz_handoff_releases_and_reacquires_paired_authority(self):
        blitz_handoff = _read(_STEER_DIR / "blitz-handoff.md")
        release_at = blitz_handoff.index("yoke claims steering release")
        reacquire_at = blitz_handoff.index("yoke claims steering acquire")
        link_at = blitz_handoff.index("yoke strategy execution link")
        assert link_at < release_at < reacquire_at

    def test_loop_covers_recovery_batching_and_handoff_snapshot(self):
        loop = _read(_STEER_DIR / "loop.md")
        batches = _read(_STEER_DIR / "release-batches.md")
        assert "<!-- YOKE:HARNESS claude start -->" in loop
        assert "ScheduleWakeup" in loop
        assert "yoke session-control evidence get --session SESSION-ID" in loop
        assert "yoke session-control session wake --item PREFIX-N" in loop
        assert "cursor-agent --resume" not in loop
        assert "`completed`" in loop
        assert "yoke claims work acquire --item PREFIX-N --reason steering" in loop
        assert "deployment-runs create" in batches
        assert "--source-ref {PINNED_SHA}" in batches
        assert "yoke merge item PREFIX-N --result" in batches
        assert "`--skip-deploy`" in batches
        assert "--item PREFIX-N --stage STAGE" in batches
        assert (
            'yoke strategy coordination append {SLUG} --section "Live Status" '
            '--entry "{current status and next steps}"'
        ) in loop


class TestSteerArgumentHint:
    def test_argument_hint_marks_the_slug_optional(self):
        frontmatter = _read(_STEER_DIR / "SKILL.md").split("---", 2)[1]
        assert 'argument-hint: "[STRATEGY-DOC-SLUG] [--project P ...]"' in frontmatter
