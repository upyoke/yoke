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
    """Collapse wrapping so a prose assertion is about words, not line breaks."""
    return " ".join(text.split())


def _corpus() -> str:
    return "".join(_read(path) for path in sorted(_STEER_DIR.glob("*.md")))


class TestSteerSkillContract:
    def test_skill_id_is_steer_not_coordinate(self):
        text = _read(_STEER_DIR / "SKILL.md")
        assert text.startswith("---")
        assert "name: steer" in text.split("---", 2)[1]
        assert "# /yoke steer" in text

    def test_strategy_doc_resolves_and_is_offered_only_when_absent(self):
        text = _corpus()
        assert "STRATEGY-DOC-SLUG" in text
        assert "no doc-less" in text.lower()
        assert "offer to" in text.lower()
        assert "yoke strategy doc create" in text
        assert "# Objective" in text
        assert "# Frontier" in text
        assert "# Decisions" in text
        assert "# Gates" in text
        assert "Use `--doc` instead of `--plan-doc` when the operator named" in (
            _words(text)
        )
        assert "yoke strategy doc-claim acquire" not in text

    def test_a_project_level_request_locks_the_plan(self):
        skill = _words(_corpus())
        assert (
            "yoke claims steering acquire --project {_project} --plan-doc {SLUG}"
        ) in skill
        assert "Proceed only with both halves held." in skill

    def test_vocabulary_is_steering_not_coordination(self):
        corpus = _corpus()
        assert "yoke claims steering acquire" in corpus
        assert "coordination-scope" not in corpus
        assert "coordinator claim" not in corpus
        assert "coordination_scope" not in corpus

    def test_does_not_invoke_feed(self):
        assert "no `/yoke feed`" in _corpus()

    def test_loop_covers_frontier_reports_doc_blitz_staffing_escalate(self):
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
        assert "unclaimed" in loop

    def test_each_pass_reads_plan_and_report_before_messages(self):
        loop = _read(_STEER_DIR / "loop.md")
        loop_words = _words(loop)
        assert loop.index("yoke strategy doc get {SLUG}") < loop.index(
            "yoke charge schedule"
        )
        assert loop.index("yoke steering report get") < loop.index("yoke messages list")
        assert "Routine resume reads only the Live Status" in loop_words
        assert "The doc wins on scope, priority and order" in loop_words
        assert "the DB wins on live status, claims and eligibility" in loop_words
        scope = _words(_read(_STEER_DIR / "scope-and-authority.md"))
        assert "cold-start refresh" in scope
        assert "open-work index" in scope

    def test_the_report_is_the_detector_and_the_loop_does_not_re_query_it(self):
        raw = _read(_STEER_DIR / "loop.md")
        loop = _words(raw)
        assert "yoke steering report get" in loop
        assert "Act on every report finding" in loop
        assert "FROM session_message_recipients r JOIN harness_sessions" not in raw
        assert "FROM work_claims c JOIN harness_sessions s" not in raw
        assert "FROM session_messages m JOIN session_message_recipients r" not in raw
        assert "FROM items i LEFT JOIN work_claims c" not in raw
        assert "FROM session_launches" not in raw

    def test_every_reported_finding_names_what_to_do_with_it(self):
        findings = _words(_read(_STEER_DIR / "fleet-findings.md"))
        for finding in (
            "**Available",
            "**Idle holder**",
            "**Undelivered message**",
            "**Stranded or vendor-stopped**",
            "**Unregistered or abandoned launch**",
            "**Landed without close-out**",
            "**Dead wait**: answer for the ended session",
        ):
            assert finding in findings
        assert "never a duplicate create" in findings
        assert "Plan limits do not gate launch" in findings

    def test_every_idle_holder_alarm_gets_an_action_or_a_disposition(self):
        loop = _words(_read(_STEER_DIR / "loop.md"))
        assert "Act on each `fleet ALARM` line the same turn" in loop
        assert "act, or write one line saying why the wait is still sound" in loop
        assert "`native_process_gone` means wake, not terminate" in loop
        lifecycle = _words(_read(_STEER_DIR / "worker-lifecycle.md"))
        assert "Message a quiet worker first." in lifecycle

    def test_the_loop_rechecks_ownership_and_holds_work_explicitly(self):
        loop = _words(_read(_STEER_DIR / "loop.md"))
        assert "recheck the holder, then launch" in loop
        assert "yoke items freeze PREFIX-N" in loop
        assert "yoke items cancel PREFIX-N --reason TEXT" in loop

    def test_no_steer_file_teaches_the_retired_label_or_snapshot_reads(self):
        corpus = _corpus()
        assert "**Stale claim holders:**" not in corpus
        assert "**Silent in-flight work:**" not in corpus
        assert "liveness=stale" not in corpus

    def test_no_steer_file_teaches_steerer_sent_only_scope(self):
        corpus = _corpus()
        assert "every envelope this steerer sent" not in corpus

    def test_blitz_handoff_releases_and_reacquires_paired_authority(self):
        blitz_handoff = _read(_STEER_DIR / "blitz-handoff.md")
        release_at = blitz_handoff.index("yoke claims steering release")
        reacquire_at = blitz_handoff.index("yoke claims steering acquire")
        link_at = blitz_handoff.index("yoke strategy execution link")
        assert link_at < release_at < reacquire_at

    def test_operator_escalation_path_waits(self):
        loop = _words(_read(_STEER_DIR / "loop.md"))
        assert "present evidence and a recommendation, then wait" in loop
        assert "Never guess, implement or file a substitute item" in loop

    def test_loop_covers_recovery_batching_and_handoff_snapshot(self):
        loop = _read(_STEER_DIR / "loop.md")
        batches = _read(_STEER_DIR / "release-batches.md")
        assert "<!-- YOKE:HARNESS claude start -->" in loop
        assert "ScheduleWakeup" in loop
        assert "yoke session-control evidence get --session SESSION-ID" in loop
        assert "yoke session-control session wake --item PREFIX-N" in loop
        assert "cursor-agent --resume" not in loop
        assert "released `completed`" in loop
        assert "yoke claims work acquire --item PREFIX-N --reason steering" in loop
        assert "An `activation` edge sends no go-signal" in loop
        assert "deployment-runs create" in batches
        assert "--source-ref {PINNED_SHA}" in batches
        assert "yoke merge item PREFIX-N --result" in batches
        assert "never `--skip-deploy`" in batches
        assert "orphaned release-wait member" in batches
        assert "--stage STAGE --member PREFIX-N" in batches
        assert (
            "## Live status — steering snapshot (refresh or replace on "
            "next steering handoff)"
        ) in loop


class TestNearTermPlanDefault:
    """An omitted slug selects CURRENT-PLAN instead of asking the operator."""

    def test_omitted_slug_resolves_to_current_plan_without_asking(self):
        scope = _words(_read(_STEER_DIR / "scope-and-authority.md"))
        assert "The slug is the operator's, else `CURRENT-PLAN`; never ask." in scope

    def test_only_a_genuinely_missing_document_reaches_the_create_gate(self):
        scope = _words(_read(_STEER_DIR / "scope-and-authority.md"))
        assert "A missing doc (not a failed read): offer to create it" in scope
        assert "no means stop" in scope

    def test_resolved_document_is_read_before_any_steering_action(self):
        scope = _words(_read(_STEER_DIR / "scope-and-authority.md"))
        assert "Read the doc before acting." in scope
        assert "decisions, holds, gates and open-work index" in scope

    def test_each_named_project_takes_its_own_document_and_seat(self):
        scope = _words(_read(_STEER_DIR / "scope-and-authority.md"))
        assert "Repeat per project." in scope

    def test_argument_hint_marks_the_slug_optional(self):
        frontmatter = _read(_STEER_DIR / "SKILL.md").split("---", 2)[1]
        assert 'argument-hint: "[STRATEGY-DOC-SLUG] [--project P ...]"' in frontmatter
        assert "defaulting to CURRENT-PLAN" in frontmatter
