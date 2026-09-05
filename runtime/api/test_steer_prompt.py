"""Static regression coverage for the /yoke steer prompt surface."""

from __future__ import annotations

from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_STEER_DIR = _REPO_ROOT / ".agents" / "skills" / "yoke" / "steer"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


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
        assert "Avoid the bare phrase" in text
        assert "steer claim" in text

    def test_strategy_doc_resolves_and_is_offered_only_when_absent(self):
        text = _read(_STEER_DIR / "SKILL.md")
        assert "STRATEGY-DOC-SLUG" in text
        assert "no doc-less" in text.lower()
        assert "offer to" in text.lower()
        assert "yoke strategy doc create" in text
        assert "# Objective" in text
        assert "# Frontier" in text
        assert "# Decisions" in text
        assert "# Gates" in text
        assert "yoke claims steering acquire --project {_project} --doc {SLUG}" in text
        assert "yoke strategy doc-claim acquire" not in text

    def test_a_project_level_request_locks_the_plan_without_narrowing(self):
        """The default slug must not shrink what the seat steers."""
        skill = _words(_read(_STEER_DIR / "SKILL.md"))
        assert (
            "yoke claims steering acquire --project {_project} --plan-doc {SLUG}"
        ) in skill
        assert "Reading a document and covering a scope are two decisions" in skill
        assert (
            '`--plan-doc` leaves the scope `{"project_id": N}`, so the seat '
            "covers every item in the project"
        ) in skill
        assert (
            "choose it only when the operator asked to steer that document"
        ) in skill

    def test_vocabulary_is_steering_not_coordination(self):
        corpus = _corpus()
        assert "steering-scope claim" in corpus
        assert "steering claim holder" in corpus
        assert "steering scope" in corpus
        assert "claims.steering.acquire" in corpus
        assert "yoke claims steering acquire" in corpus
        assert "coordination-scope" not in corpus
        assert "coordinator claim" not in corpus
        assert "coordination_scope" not in corpus

    def test_does_not_invoke_feed(self):
        corpus = _corpus()
        assert "Do not invoke `/yoke feed`" in corpus
        assert "unrelated" in corpus.lower()

    def test_loop_covers_frontier_reports_doc_blitz_staffing_escalate(self):
        loop = _read(_STEER_DIR / "loop.md")
        blitz_handoff = _read(_STEER_DIR / "blitz-handoff.md")
        assert "yoke charge schedule" in loop
        assert "yoke say --item PREFIX-N --stdin" in loop
        assert "yoke messages acknowledge" in loop
        assert "yoke strategy doc get" in loop
        assert "blitz-handoff" in loop
        assert "yoke strategy execution link" in blitz_handoff
        assert "yoke claims steering release" in blitz_handoff
        assert "yoke steering report get" in loop
        assert "unclaimed" in loop
        assert "Escalate" in loop
        assert "wait" in loop.lower()

    def test_each_pass_reads_plan_before_frontier_and_reconciles_authority(self):
        skill = _read(_STEER_DIR / "SKILL.md")
        loop = _read(_STEER_DIR / "loop.md")
        skill_words = _words(skill)
        loop_words = _words(loop)
        assert loop.index("yoke strategy doc get {SLUG}") < loop.index(
            "yoke charge schedule"
        )
        assert "Each pass reads every claimed document first" in loop_words
        assert "document wins on intended scope, priority, order" in loop_words
        assert "DB wins" in loop_words
        assert "live item status, claims, dependencies" in loop_words
        assert "does not silently become next" in loop_words
        assert "durable write target" in loop_words
        assert "plan-level progress" in loop_words
        assert "Strategy doc is both input and output" in skill_words
        assert "cold-start refresh" in skill_words
        assert "open-work index" in skill_words
        assert (
            "standing decision, hold, scope bound, and deployment gate that "
            "constrains action"
        ) in skill_words

    def test_negative_space_checks_run_first_and_unconditionally(self):
        loop = _words(_read(_STEER_DIR / "loop.md"))
        assert "Negative-space checks — first, every periodic pass" in loop
        assert "before consuming events, messages, or worker reports" in loop
        assert "Failures arrive as silence" in loop

    def test_the_report_is_the_detector_and_the_loop_does_not_re_query_it(self):
        """The duplication this section used to carry is the failure itself.

        A steering seat with the report on screen re-ran its checks by hand
        because the loop still taught them, so the loop must route to the
        report rather than restate what it already answers.
        """
        raw = _read(_STEER_DIR / "loop.md")
        loop = _words(raw)
        assert "the fleet report is the detector" in loop
        assert "yoke steering report get" in loop
        assert "Do not re-run those queries by hand" in loop
        assert "open the file, not the preview" in loop
        # The hand queries this section used to carry are gone entirely.
        assert "FROM session_message_recipients r JOIN harness_sessions" not in raw
        assert "FROM work_claims c JOIN harness_sessions s" not in raw
        assert "FROM session_messages m JOIN session_message_recipients r" not in raw
        assert "FROM items i LEFT JOIN work_claims c" not in raw

    def test_every_reported_finding_names_what_to_do_with_it(self):
        loop = _words(_read(_STEER_DIR / "loop.md"))
        for finding in (
            "**Available work**",
            "**Unacked injected (this session)**",
            "**Idle holders**",
            "**Undelivered messages**",
            "**Vendor-stopped sessions**",
            "**Unregistered launches**",
            "**Landed without close-out**",
            "**Dead waits**",
            "**Plan limits**",
        ):
            assert finding in loop
        assert "A section with nothing to say prints nothing" in loop

    def test_unregistered_launches_use_the_registered_list_read(self):
        raw = _read(_STEER_DIR / "loop.md")
        loop = _words(raw)
        assert "yoke session-control launch list --project" in loop
        assert "session_control.launch.list" in loop
        assert "session_launches" in loop
        assert "session_control_launches" in raw
        assert "does not exist" in loop
        assert "FROM session_launches" not in raw

    def test_starved_holder_triage_reads_the_stale_reclaim_clock(self):
        loop = _words(_read(_STEER_DIR / "loop.md"))
        assert "stale_eligible_at" in loop
        assert "effective_stale_ttl_minutes" in loop
        assert "yoke sessions list --json" in loop
        assert "near reclaim is revived before anything else in the pass" in loop

    def test_a_parked_holder_declared_its_wait(self):
        loop = _words(_read(_STEER_DIR / "loop.md"))
        assert "`--mode parked` declared its wait" in loop

    def test_dead_wait_rows_separate_no_reply_coming_from_still_open(self):
        loop = _words(_read(_STEER_DIR / "loop.md"))
        assert "means no reply is coming" in loop
        assert "answer on the ended session's behalf" in loop
        assert "the current state of whatever it was waiting on" in loop
        # An unresolved row is context for the probe, never a finding to act on.
        assert "`unresolved` row is an open question with a live answerer" in loop
        assert "a wake alone parks it on the same question" in loop

    def test_the_loop_keeps_only_what_the_report_does_not_do(self):
        loop = _words(_read(_STEER_DIR / "loop.md"))
        assert "Two things the report deliberately does not do" in loop
        # Ownership is re-verified after the report, immediately before acting.
        assert "Re-verify ownership immediately before launching or reclaiming" in loop
        assert "one more claim handoff window" in loop
        assert "staffed a second worker onto a healthy item" in loop
        report_at = loop.index("the fleet report is the detector")
        assert loop.index("yoke claims work holder-get PREFIX-N", report_at) > report_at
        # A deliberate hold is the operator's flag, not something to infer.
        assert "Set the hold flag on work you are holding on purpose" in loop
        assert "rather than guessing intent" in loop
        assert "yoke items freeze PREFIX-N" in loop
        assert "yoke items cancel PREFIX-N --reason TEXT" in loop

    def test_dashboard_card_is_named_as_the_faster_read(self):
        loop = _words(_read(_STEER_DIR / "loop.md"))
        assert "dashboard session card" in loop
        # The server owns liveness while the copy distinguishes recent from
        # quiet activity within sessions that are still alive.
        assert "`active now` under a minute" in loop
        assert "`idle <age>` once quiet" in loop
        assert "`stale <age>`" in loop
        assert "`waiting` / `probed` / `possibly stale`" in loop
        assert "executor-aware TTL (1440 minutes on this surface)" in loop
        assert "solely decides alive versus stale" in loop
        assert "The age says how long it has been quiet" in loop

    def test_no_steer_file_teaches_the_retired_label_or_snapshot_reads(self):
        corpus = _corpus()
        assert "**Stale claim holders:**" not in corpus
        assert "**Silent in-flight work:**" not in corpus
        # The report's idle detector keys on last activity, never on liveness:
        # the card uses liveness only for alive-versus-stale classification,
        # and a 1440-minute TTL is the wrong clock for deciding a worker has
        # stopped moving.
        assert "liveness=stale" not in corpus
        assert "rather than any liveness label" in _words(corpus)
        assert "The age says how long it has been quiet" in _words(corpus)

    def test_no_steer_file_teaches_steerer_sent_only_scope(self):
        corpus = _corpus()
        assert "every envelope this steerer sent" not in corpus

    def test_steering_seat_is_the_only_staffing_path(self):
        loop = _read(_STEER_DIR / "loop.md")
        assert "unclaimed" in loop
        assert "yoke steering report get" in loop
        assert "this seat's to staff; nothing else" in loop
        lifecycle = _read(_STEER_DIR / "worker-lifecycle.md")
        assert "There is no second staffing" in lifecycle

    def test_blitz_handoff_releases_and_reacquires_paired_authority(self):
        blitz_handoff = _read(_STEER_DIR / "blitz-handoff.md")
        release_at = blitz_handoff.index("yoke claims steering release")
        reacquire_at = blitz_handoff.index("yoke claims steering acquire")
        link_at = blitz_handoff.index("yoke strategy execution link")
        assert link_at < release_at < reacquire_at
        assert "atomically releases the document lock" in blitz_handoff

    def test_operator_escalation_path_waits(self):
        loop = _read(_STEER_DIR / "loop.md")
        assert "Escalate only human decisions" in loop
        assert "wait" in loop.lower()
        assert "Do not guess" in loop

    def test_loop_covers_recovery_batching_and_handoff_snapshot(self):
        loop = _read(_STEER_DIR / "loop.md")
        assert "<!-- YOKE:HARNESS claude start -->" in loop
        assert "ScheduleWakeup" in loop
        assert "session_message_recipients" in loop
        assert "cursor-agent --resume <session-id>" in loop
        assert "Negative-space checks — first, every periodic pass" in loop
        assert "injection_count=0" in loop
        assert "failures are silences" in loop
        assert "release_reason=completed" in loop
        assert "yoke claims work acquire --item PREFIX-N --reason steering" in loop
        assert "activation dependencies do not send their own go-signal" in loop
        assert "deployment-runs create" in loop
        assert "--source-ref {PINNED_SHA}" in loop
        assert "yoke watch merge done-transition -- PREFIX-N" in loop
        assert (
            "## Live status — steering snapshot "
            "(refresh or replace on next steering handoff)" in loop
        )


class TestNearTermPlanDefault:
    """An omitted slug selects CURRENT-PLAN instead of asking the operator."""

    def test_omitted_slug_resolves_to_current_plan_without_asking(self):
        skill = _words(_read(_STEER_DIR / "SKILL.md"))
        assert "`{SLUG}` is `CURRENT-PLAN` for every resolved project" in skill
        assert "An omitted slug is not a question to ask" in skill

    def test_explicitly_supplied_slug_wins_over_the_default(self):
        skill = _words(_read(_STEER_DIR / "SKILL.md"))
        assert "An operator-supplied slug wins" in skill
        assert "an explicitly supplied slug always wins" in skill

    def test_only_a_genuinely_missing_document_reaches_the_create_gate(self):
        skill = _words(_read(_STEER_DIR / "SKILL.md"))
        assert (
            "Only a genuinely missing document reaches this gate; an omitted "
            "slug never does, because it already resolved to `CURRENT-PLAN`"
        ) in skill

    def test_resolved_document_is_read_before_any_steering_action(self):
        skill = _words(_read(_STEER_DIR / "SKILL.md"))
        assert (
            "Read `{SLUG}` before any steering action — before the frontier, "
            "before acknowledging reports, before staffing anything"
        ) in skill
        assert (
            "standing decisions, holds, scope bounds, and deployment gates"
        ) in skill

    def test_each_named_project_takes_its_own_document_and_seat(self):
        skill = _words(_read(_STEER_DIR / "SKILL.md"))
        assert "Several projects mean several seats" in skill
        assert "There is no multi-project seat" in skill
        assert (
            "run steps 2 and 3 once per project so each gets its own resolved "
            "document and its own seat"
        ) in skill

    def test_argument_hint_marks_the_slug_optional(self):
        frontmatter = _read(_STEER_DIR / "SKILL.md").split("---", 2)[1]
        assert 'argument-hint: "[STRATEGY-DOC-SLUG] [--project P ...]"' in frontmatter
        assert "defaulting to CURRENT-PLAN" in frontmatter


class TestNearTermPlanDefaultAcrossTeachingSurfaces:
    """Router, help, command reference, and packet teach the same default."""

    SURFACES = (
        _REPO_ROOT / ".agents" / "skills" / "yoke" / "SKILL.md",
        _REPO_ROOT / ".agents" / "skills" / "yoke" / "help" / "SKILL.md",
        _REPO_ROOT / "docs" / "public" / "reference" / "commands.md",
        _REPO_ROOT / ".yoke" / "docs" / "reference" / "commands.md",
        _REPO_ROOT / "docs" / "harness-bootstrap.md",
        _REPO_ROOT
        / "packages"
        / "yoke-core"
        / "src"
        / "yoke_core"
        / "domain"
        / "schema_api_context_commands_claims.py",
    )

    def test_no_surface_still_calls_the_strategy_doc_required(self):
        for path in self.SURFACES:
            text = _words(_read(path))
            assert "required strategy doc" not in text, path
            assert "a strategy doc is required" not in text, path

    def test_every_surface_names_the_default(self):
        for path in self.SURFACES:
            assert "CURRENT-PLAN" in _read(path), path
