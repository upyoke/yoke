"""Static regression coverage for the /yoke steer prompt surface."""

from __future__ import annotations

from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_STEER_DIR = _REPO_ROOT / ".agents" / "skills" / "yoke" / "steer"
_ROUTER = _REPO_ROOT / ".agents" / "skills" / "yoke" / "SKILL.md"
_HELP = _REPO_ROOT / ".agents" / "skills" / "yoke" / "help" / "SKILL.md"
_CLAIMS_PACKET = (
    _REPO_ROOT
    / "packages"
    / "yoke-core"
    / "src"
    / "yoke_core"
    / "domain"
    / "schema_api_context_commands_claims.py"
)


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

    def test_strategy_doc_is_required_and_offered_if_absent(self):
        text = _read(_STEER_DIR / "SKILL.md")
        assert "STRATEGY-DOC-SLUG" in text
        assert "no doc-less" in text.lower()
        assert "offer to" in text.lower()
        assert "yoke strategy doc create" in text
        assert "# Objective" in text
        assert "# Frontier" in text
        assert "# Decisions" in text
        assert "# Gates" in text

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
        assert "yoke strategy doc-claim release" in blitz_handoff
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
        assert "Each pass reads the claimed document first" in loop_words
        assert "document wins on intended scope, priority, order" in loop_words
        assert "DB wins" in loop_words
        assert "live item status, claims, dependencies" in loop_words
        assert "does not silently become next" in loop_words
        assert "durable write target" in loop_words
        assert "plan-level progress" in loop_words
        assert "Strategy doc is both input and output" in skill_words
        assert "cold-start refresh" in skill_words
        assert "open-work index" in skill_words
        assert "standing decision that constrains action" in skill_words

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
        # The hand queries this section used to carry are gone entirely.
        assert "FROM session_message_recipients r JOIN harness_sessions" not in raw
        assert "FROM work_claims c JOIN harness_sessions s" not in raw
        assert "FROM session_messages m JOIN session_message_recipients r" not in raw
        assert "FROM items i LEFT JOIN work_claims c" not in raw

    def test_every_reported_finding_names_what_to_do_with_it(self):
        loop = _words(_read(_STEER_DIR / "loop.md"))
        for finding in (
            "**Available work**",
            "**Idle holders**",
            "**Starved delivery**",
            "**Unregistered launches**",
            "**Landed without close-out**",
            "**Dead waits**",
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

    def test_dashboard_card_is_named_as_the_faster_read(self):
        loop = _words(_read(_STEER_DIR / "loop.md"))
        assert "dashboard session card" in loop
        assert "`idle <age>`" in loop
        assert "`waiting` / `probed` / `possibly stale`" in loop
        assert "Read the idle age, not the pill" in loop
        assert "1440-minute clock" in loop

    def test_no_steer_file_teaches_the_retired_label_or_snapshot_reads(self):
        corpus = _corpus()
        assert "**Stale claim holders:**" not in corpus
        assert "**Silent in-flight work:**" not in corpus
        # The liveness label is gone from the steer corpus entirely: idleness
        # is the report's to detect, and it keys on last activity instead.
        assert "liveness=stale" not in corpus
        assert "rather than any liveness label" in _words(corpus)
        assert "makes the liveness label useless" in _words(corpus)

    def test_no_steer_file_teaches_steerer_sent_only_scope(self):
        corpus = _corpus()
        assert "every envelope this steerer sent" not in corpus

    def test_steering_seat_is_the_only_staffing_path(self):
        loop = _read(_STEER_DIR / "loop.md")
        assert "unclaimed" in loop
        assert "yoke steering report get --project" in loop
        assert "this seat's to staff; nothing else" in loop
        lifecycle = _read(_STEER_DIR / "worker-lifecycle.md")
        assert "There is no second staffing" in lifecycle

    def test_blitz_handoff_releases_the_document_lock(self):
        blitz_handoff = _read(_STEER_DIR / "blitz-handoff.md")
        release_at = blitz_handoff.index("yoke strategy doc-claim release")
        link_at = blitz_handoff.index("yoke strategy execution link")
        assert link_at < release_at
        assert "mutually exclusive" in blitz_handoff

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


class TestSteerWorkerLifecycle:
    def test_worker_rules_and_launcher_recipe_cover_steering_contract(self):
        text = _read(_STEER_DIR / "worker-lifecycle.md")
        assert "Encode dependency edges" in text
        assert "Keep the frontier maxed out" in text
        assert "Launch CLI surfaces only" in text
        assert "Route one item through its pinned workflow" in text
        assert "Workers self-end after their DONE message" in text
        assert "Every new item gets a fresh session" in text
        assert "Choose the model per item at launch" in text
        assert "yoke session-control launch create" in text
        assert "yoke session-control launch get" in text
        assert "yoke session-control launch reconcile" in text
        assert "yoke session-control launch retry" in text
        assert "claude-cli" in text
        assert "codex-cli" in text
        assert "cursor-cli" in text
        assert "balanced across all three CLI surfaces" in text
        assert "preferred_session_models" in text
        assert "yoke sessions terminate" in text
        assert "reserved for an unresponsive worker" in text
        assert "Single-item mandate (steering)" in text
        assert "Do NOT create or dispatch any deployment run" in text
        assert "yoke workflows item get PREFIX-N" in text
        assert "/yoke refine PREFIX-N" in text
        assert "/yoke blitz PREFIX-N" in text
        assert "/yoke shepherd" in text
        assert "yoke say --item PREFIX-N --stdin" in text
        assert "yoke say --stdin --session" in text
        assert "Never expand a truncated session id" in text
        assert "yoke session-control launch preview" in text
        assert "session_control.launch.preview" in _read(_STEER_DIR / "SKILL.md")
        assert "session_control.launch.list" in _read(_STEER_DIR / "SKILL.md")

    def test_surfaces_are_not_exclusive_and_balance_is_not_a_quota(self):
        text = _words(_read(_STEER_DIR / "worker-lifecycle.md"))
        assert "Surfaces are not exclusive" in text
        assert "as many concurrent sessions as the work needs" in text
        assert "one-session-per-surface cap" in text
        assert "not a quota" in text
        assert "never withholds a launch" in text
        assert "it never withholds one" in text

    def test_launch_preview_is_mandatory_and_names_surface_refusals(self):
        text = _words(_read(_STEER_DIR / "worker-lifecycle.md"))
        assert "Preview the chosen CLI surface before every launch" in text
        assert "never the calling session's own surface" in text
        assert "unsupported_surface" in text
        assert "A refusal names the surface, not the item" in text
        assert "launchable=true" in text
        assert "Do not create until preview returns" in text


class TestSteerDiscoveryAndPacket:
    def test_router_and_help_name_steer(self):
        assert "/yoke steer" in _read(_ROUTER)
        assert "/yoke steer" in _read(_HELP)

    def test_packet_teaches_steer_loop_and_fleet_report(self):
        notes = _read(_CLAIMS_PACKET)
        assert "/yoke steer SLUG" in notes
        assert "offer to create if absent" in notes
        assert "yoke steering report get --project P" in notes
        assert "never `/yoke do`" in notes
        assert "yoke say --item PREFIX-N --stdin" in notes
