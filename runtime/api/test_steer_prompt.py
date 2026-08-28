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


def _sql_after(text: str, marker: str) -> str:
    """Return the single-line `yoke db read` statement containing `marker`."""
    at = text.index(marker)
    return text[text.rindex('yoke db read "', 0, at) : text.index('"\n', at)]


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

    def test_loop_covers_frontier_reports_doc_blitz_backstop_escalate(self):
        loop = _read(_STEER_DIR / "loop.md")
        assert "yoke charge schedule" in loop
        assert "yoke say --item PREFIX-N --stdin" in loop
        assert "yoke messages acknowledge" in loop
        assert "yoke strategy doc get" in loop
        assert "yoke strategy execution link" in loop
        assert "yoke strategy doc-claim release" in loop
        assert "blitz-handoff" in loop
        assert "yoke steering backstop evaluate" in loop
        assert "unclaimed" in loop
        assert "Escalate" in loop
        assert "wait" in loop.lower()

    def test_each_pass_reads_plan_before_frontier_and_reconciles_authority(self):
        skill = _read(_STEER_DIR / "SKILL.md")
        loop = _read(_STEER_DIR / "loop.md")
        skill_words = " ".join(skill.split())
        loop_words = " ".join(loop.split())
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

    def test_negative_space_checklist_runs_first_and_unconditionally(self):
        loop = _read(_STEER_DIR / "loop.md")
        assert "Negative-space checks — first, every periodic pass" in loop
        assert "before consuming events, messages, or worker reports" in loop
        assert "the events wait and the checklist still runs" in loop
        assert "Event handling expands to fill the pass" in loop

    def test_outbound_delivery_check_covers_every_sender(self):
        loop = _read(_STEER_DIR / "loop.md")
        assert "Sender is not a filter" in loop
        assert "worker-to-steerer envelopes starve" in loop
        assert "recipient idleness is the whole trigger" in loop
        # The sweep query selects on recipient idleness, never on who sent it.
        query_at = loop.index("FROM session_message_recipients r JOIN harness_sessions")
        query = loop[query_at : loop.index('"', query_at)]
        assert "sender" not in query
        assert "s.last_tool_call_at" in query

    def test_starved_holder_triage_reads_the_stale_reclaim_clock(self):
        loop = _read(_STEER_DIR / "loop.md")
        assert "stale_eligible_at" in loop
        assert "effective_stale_ttl_minutes" in loop
        assert "yoke sessions list --json" in loop
        assert "near reclaim is revived before anything else in the pass" in loop

    def test_quiet_holder_check_is_idle_duration_not_liveness_label(self):
        loop = _read(_STEER_DIR / "loop.md")
        assert "**Idle claim holders:**" in loop
        assert "older than **20 minutes**" in loop
        assert "Never key this check on `liveness=stale`" in loop
        assert "1440-minute stale TTL" in loop
        # The runnable query keys on elapsed idle time, never on the label.
        query = _sql_after(loop, "FROM work_claims c JOIN harness_sessions s")
        assert "s.last_tool_call_at::timestamptz < now() - interval '20 minutes'" in query
        assert "liveness" not in query
        # A holder that declared its wait is not idle.
        assert "s.mode <> 'parked'" in query

    def test_dead_wait_check_names_the_ended_answerer_and_its_resolution(self):
        loop = _read(_STEER_DIR / "loop.md")
        assert "**Dead waits:**" in loop
        assert "answerer_ended_at" in loop
        assert "no reply is coming" in loop
        assert "Answer on the ended session's behalf" in loop
        assert "the current state of whatever it was" in loop
        query = _sql_after(loop, "FROM session_messages m JOIN session_message_recipients r")
        assert "m.sender_session_id = '{IDLE_SESSION_ID}'" in query
        assert "a.ended_at AS answerer_ended_at" in query

    def test_ownership_check_requires_sustained_unowned_time_and_a_reverify(self):
        loop = _read(_STEER_DIR / "loop.md")
        assert "**Unowned in-flight work:**" in loop
        assert "unowned **continuously past 15 minutes**" in loop
        assert "Never act on a snapshot" in loop
        # The duplicate-launch incident is the reason the guard exists.
        assert "staffed a second worker onto a healthy item" in loop
        assert "refused to override and reported the conflict" in loop
        query = _sql_after(loop, "FROM items i LEFT JOIN work_claims c")
        assert "interval '15 minutes'" in query
        # Re-verify happens immediately before acting, after the sweep.
        sweep_at = loop.index("**Unowned in-flight work:**")
        reverify_at = loop.index("yoke claims work holder-get PREFIX-N", sweep_at)
        assert "re-verify ownership immediately before launching or reclaiming" in loop
        assert reverify_at > loop.index("FROM items i LEFT JOIN work_claims c")

    def test_dashboard_card_is_named_as_the_faster_read(self):
        loop = _read(_STEER_DIR / "loop.md")
        assert "dashboard session card" in loop
        assert "`idle <age>`" in loop
        assert "`waiting` / `probed` / `possibly stale`" in loop
        assert "Read the idle age, not the pill" in loop
        assert "headless pass" in loop

    def test_no_steer_file_teaches_the_retired_label_or_snapshot_reads(self):
        corpus = _corpus()
        assert "**Stale claim holders:**" not in corpus
        assert "**Silent in-flight work:**" not in corpus
        # `liveness=stale` survives only as the explicit do-not-use warning.
        assert corpus.count("liveness=stale") == 1
        assert "Never key this check on `liveness=stale`" in corpus

    def test_no_steer_file_teaches_steerer_sent_only_scope(self):
        corpus = _corpus()
        assert "every envelope this steerer sent" not in corpus

    def test_backstop_is_only_for_unpicked_work(self):
        loop = _read(_STEER_DIR / "loop.md")
        assert "unclaimed" in loop
        assert "yoke steering backstop evaluate --project" in loop
        assert "safety net for work that sat" in loop

    def test_blitz_handoff_releases_the_document_lock(self):
        loop = _read(_STEER_DIR / "loop.md")
        release_at = loop.index("yoke strategy doc-claim release")
        link_at = loop.index("yoke strategy execution link")
        assert link_at < release_at
        assert "mutually exclusive" in loop

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


class TestSteerDiscoveryAndPacket:
    def test_router_and_help_name_steer(self):
        assert "/yoke steer" in _read(_ROUTER)
        assert "/yoke steer" in _read(_HELP)

    def test_packet_teaches_steer_loop_and_backstop(self):
        notes = _read(_CLAIMS_PACKET)
        assert "/yoke steer SLUG" in notes
        assert "offer to create if absent" in notes
        assert "yoke steering backstop evaluate --project P" in notes
        assert "never `/yoke do`" in notes
        assert "yoke say --item PREFIX-N --stdin" in notes
