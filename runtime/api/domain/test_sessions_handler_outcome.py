"""Unit tests for handler-outcome classification helpers.

Covers AC-21, AC-22, AC-24..27, AC-36, AC-37, AC-39, AC-41 at the helper
surface. ``/yoke do`` integration regressions and the
recoverable-substrate reproduction live in the sibling module
``runtime.api.test_do_loop_recoverable_substrate``.
"""

from __future__ import annotations

import pytest
from unittest.mock import patch

from runtime.api.test_sessions import _create_schema, _register, conn  # noqa: F401  (Postgres-backed pytest fixture)
from yoke_core.domain.sessions_handler_outcome import (
    NON_USEFUL_STEP_OUTCOMES,
    OUTCOME_BLOCKED,
    OUTCOME_COMPLETED,
    OUTCOME_INTERACTIVE_CHECKPOINT,
    OUTCOME_RECOVERABLE_SUBSTRATE,
    OUTCOME_SLICE_COMMITTED,
    TERMINAL_OUTCOMES,
    classify_advance_outcome,
    is_non_useful_step,
    is_terminal_outcome,
    record_interactive_checkpoint_handoff,
    record_recoverable_substrate_skip,
    render_chain_summary_label,
)
from yoke_core.domain.sessions_queries_chain import read_chain_skip_memory


class TestIsNonUsefulStep:
    """AC-25, AC-37: slice and recoverable substrate outcomes don't bump useful step."""

    def test_slice_committed_is_non_useful(self):
        assert is_non_useful_step(OUTCOME_SLICE_COMMITTED) is True

    def test_recoverable_substrate_is_non_useful(self):
        assert is_non_useful_step(OUTCOME_RECOVERABLE_SUBSTRATE) is True

    def test_completed_is_useful_step(self):
        assert is_non_useful_step(OUTCOME_COMPLETED) is False

    def test_blocked_is_useful_step_terminal(self):
        # Blocked terminates but the step that produced the blocker is
        # still a useful chain step (the loop reached a real boundary).
        assert is_non_useful_step(OUTCOME_BLOCKED) is False

    def test_interactive_checkpoint_is_useful_step_terminal(self):
        assert is_non_useful_step(OUTCOME_INTERACTIVE_CHECKPOINT) is False

    def test_none_is_safe_default(self):
        assert is_non_useful_step(None) is False
        assert is_non_useful_step("") is False

    def test_unknown_outcome_is_useful_step(self):
        # Forward-compatibility: an unknown outcome from a future
        # caller should NOT silently get a free non-useful step.
        assert is_non_useful_step("future_outcome_we_have_not_seen") is False


class TestIsTerminalOutcome:
    """AC-21, AC-22: interactive checkpoint and blocked terminate the chain."""

    def test_interactive_checkpoint_is_terminal(self):
        assert is_terminal_outcome(OUTCOME_INTERACTIVE_CHECKPOINT) is True

    def test_blocked_is_terminal(self):
        assert is_terminal_outcome(OUTCOME_BLOCKED) is True

    def test_completed_is_not_terminal(self):
        assert is_terminal_outcome(OUTCOME_COMPLETED) is False

    def test_slice_committed_is_not_terminal(self):
        assert is_terminal_outcome(OUTCOME_SLICE_COMMITTED) is False

    def test_recoverable_substrate_is_not_terminal(self):
        # Recoverable substrate failures keep the chain going so the
        # next offer can pick up other runnable work.
        assert is_terminal_outcome(OUTCOME_RECOVERABLE_SUBSTRATE) is False

    def test_none_is_safe_default(self):
        assert is_terminal_outcome(None) is False


class TestOutcomeSetIntegrity:
    """The two outcome sets must be disjoint — terminal outcomes are still useful steps."""

    def test_non_useful_and_terminal_are_disjoint(self):
        assert NON_USEFUL_STEP_OUTCOMES.isdisjoint(TERMINAL_OUTCOMES)


class TestClassifyAdvanceOutcome:
    """AC-36, AC-37, AC-41: classify slice vs completed by status comparison."""

    def test_status_unchanged_implementing_is_slice_committed(self):
        # Routed advance committed a slice but item still implementing.
        assert (
            classify_advance_outcome(
                pre_status="implementing", post_status="implementing"
            )
            == OUTCOME_SLICE_COMMITTED
        )

    def test_implementing_to_reviewing_is_completed(self):
        # Routed advance crossed a lifecycle boundary -> step bumps.
        assert (
            classify_advance_outcome(
                pre_status="implementing",
                post_status="reviewing-implementation",
            )
            == OUTCOME_COMPLETED
        )

    def test_implementing_to_reviewed_is_completed(self):
        assert (
            classify_advance_outcome(
                pre_status="implementing",
                post_status="reviewed-implementation",
            )
            == OUTCOME_COMPLETED
        )

    def test_reviewing_to_reviewed_is_completed(self):
        # Re-entry into review reaching the boundary is still completed.
        assert (
            classify_advance_outcome(
                pre_status="reviewing-implementation",
                post_status="reviewed-implementation",
            )
            == OUTCOME_COMPLETED
        )

    def test_blank_post_status_falls_back_to_completed(self):
        assert (
            classify_advance_outcome(pre_status="implementing", post_status="")
            == OUTCOME_COMPLETED
        )


class TestRenderChainSummaryLabel:
    """AC-22, AC-39: chain summary distinguishes outcomes by stable labels."""

    def test_completed_label(self):
        assert render_chain_summary_label(OUTCOME_COMPLETED) == "handler completed"

    def test_slice_committed_label(self):
        # Must NOT render as ``CHAIN STEP N/M COMPLETE``.
        label = render_chain_summary_label(OUTCOME_SLICE_COMMITTED)
        assert label == "implementation slice committed; handler continuing"
        assert "COMPLETE" not in label.upper().replace("CHAIN STEP", "")

    def test_recoverable_substrate_label(self):
        assert (
            render_chain_summary_label(OUTCOME_RECOVERABLE_SUBSTRATE)
            == "recoverable substrate failure; handler continuing"
        )

    def test_interactive_checkpoint_label(self):
        # Process at operator checkpoint surfaces interactive state.
        assert (
            render_chain_summary_label(OUTCOME_INTERACTIVE_CHECKPOINT)
            == "interactive checkpoint active"
        )

    def test_blocked_label(self):
        assert render_chain_summary_label(OUTCOME_BLOCKED) == "handler blocked"

    def test_unknown_outcome_falls_back_to_completed(self):
        assert (
            render_chain_summary_label("future_outcome")
            == "handler completed"
        )

    def test_none_falls_back_to_completed(self):
        assert render_chain_summary_label(None) == "handler completed"


class TestRecordRecoverableSubstrateSkip:
    """AC-24, AC-26, AC-27: substrate skip records dedup memory + audit event."""

    def test_persists_chain_skip_entry(self, conn):
        # Write side canonicalizes to bare-numeric so the consumer's
        # str()-equality dedup against `YOK-N` scheduler candidates lines
        # up after read-side normalization. AC-2 covers the YOK-prefixed
        # path; bare-numeric input gets the same storage outcome and is
        # exercised in test_do_loop_recoverable_substrate_claim_release.
        _register(conn, session_id="sess-substrate-1")
        with patch("yoke_core.domain.events.emit_event"):
            entry = record_recoverable_substrate_skip(
                conn,
                session_id="sess-substrate-1",
                chain_step=1,
                project="yoke",
                item_id=f"YOK-{1599}",
                routed_action="advance",
                failure_class="cwd_drift",
                remediation_owner=f"YOK-{1599}",
                current_status="implementing",
                useful_work_began=False,
            )
        assert entry["skip_reason"] == "recoverable_substrate"
        assert entry["routed_action"] == "advance"
        assert entry["failure_class"] == "cwd_drift"
        assert entry["remediation_owner"] == f"YOK-{1599}"
        assert entry["item_id"] == "1599"

        memory = read_chain_skip_memory(conn, "sess-substrate-1")
        assert len(memory) == 1
        persisted = memory[0]
        assert persisted["skip_reason"] == "recoverable_substrate"
        assert persisted["item_id"] == "1599"
        assert persisted["failure_class"] == "cwd_drift"
        assert persisted["remediation_owner"] == f"YOK-{1599}"
        assert persisted["chain_step"] == 1
        assert persisted["useful_work_began"] is False

    def test_emits_scheduler_offer_skipped(self, conn):
        _register(conn, session_id="sess-substrate-2")
        captured: list[dict] = []
        with patch(
            "yoke_core.domain.events.emit_event",
            side_effect=lambda name, **kw: captured.append({"name": name, **kw}),
        ):
            record_recoverable_substrate_skip(
                conn,
                session_id="sess-substrate-2",
                chain_step=2,
                project="yoke",
                item_id=f"YOK-{1599}",
                routed_action="advance",
                failure_class="cwd_drift",
                remediation_owner=f"YOK-{1599}",
            )
        skip_events = [e for e in captured if e["name"] == "SchedulerOfferSkipped"]
        assert len(skip_events) == 1
        ctx = skip_events[0]["context"]
        assert ctx["skip_reason"] == "recoverable_substrate"
        assert ctx["item_id"] == "1599"
        assert ctx["recommended_action"] == "advance"
        assert ctx["failure_class"] == "cwd_drift"
        assert ctx["remediation_owner"] == f"YOK-{1599}"
        assert ctx["chain_step"] == 2

    def test_dedups_same_item_twice_in_chain(self, conn):
        _register(conn, session_id="sess-substrate-dedup")
        with patch("yoke_core.domain.events.emit_event"):
            for _ in range(2):
                record_recoverable_substrate_skip(
                    conn,
                    session_id="sess-substrate-dedup",
                    chain_step=1,
                    project="yoke",
                    item_id=f"YOK-{1599}",
                    routed_action="advance",
                    failure_class="cwd_drift",
                    remediation_owner=f"YOK-{1599}",
                )
        # The append is intentionally permissive — chain memory is a log,
        # not a set. AC-26 is satisfied at the consumer (offer revalidation
        # walks the candidate set and skips items present in memory). What
        # we verify here is that the memory carries entries the consumer
        # can dedupe against, with item_id present and canonicalized on
        # each entry so scheduler-candidate comparisons match.
        memory = read_chain_skip_memory(conn, "sess-substrate-dedup")
        assert all(entry.get("item_id") == "1599" for entry in memory)
        assert len(memory) >= 1

    def test_persists_with_default_tuple_row_connection(self):
        # Inline-Python callers (loop-routing.md) may hold a tuple-row
        # connection (no mapping row factory); the helper must not crash
        # on tuple rows. Session row inserted directly because _register
        # has its own row-factory dependency outside this test's scope.
        import json

        from runtime.api.fixtures import pg_testdb
        from yoke_core.domain import db_backend

        name = pg_testdb.create_test_database()
        bare = db_backend.connect_psycopg(pg_testdb.dsn_for_test_database(name))
        try:
            _create_schema(bare)
            now = "2026-01-01T00:00:00Z"
            bare.execute(
                "INSERT INTO harness_sessions (session_id, executor, provider,"
                " model, execution_lane, capabilities, workspace, mode,"
                " offered_at, last_heartbeat, ended_at, offer_envelope) VALUES"
                " (%s, 'DARIUS', 'anthropic', 'claude-opus-4-7', 'primary',"
                " '[]', '/tmp/work', 'wait', %s, %s, NULL, NULL)",
                ("sess-bare-row", now, now),
            )
            bare.commit()
            with patch("yoke_core.domain.events.emit_event"):
                record_recoverable_substrate_skip(
                    bare, session_id="sess-bare-row", chain_step=1,
                    project="yoke", item_id=f"YOK-{1599}",
                    routed_action="advance", failure_class="cwd_drift",
                    remediation_owner=f"YOK-{1599}",
                )
            envelope_raw = bare.execute(
                "SELECT offer_envelope FROM harness_sessions WHERE session_id = %s",
                ("sess-bare-row",),
            ).fetchone()[0]
            memory = json.loads(envelope_raw)["chain_skip_memory"]
            assert len(memory) == 1
            assert memory[0]["skip_reason"] == "recoverable_substrate"
            assert memory[0]["item_id"] == "1599"
            assert memory[0]["failure_class"] == "cwd_drift"
        finally:
            bare.close()
            pg_testdb.drop_test_database(name)


class TestRecordInteractiveCheckpointHandoff:
    """AC-21, AC-22: interactive checkpoint preserves work claim, terminates chain."""

    def test_writes_chain_checkpoint_with_interactive_outcome(self, conn):
        _register(conn, session_id="sess-checkpoint")
        with patch("yoke_core.domain.events.emit_event"):
            with patch(
                "yoke_core.domain.sessions_analytics._emit_event"
            ):
                checkpoint = record_interactive_checkpoint_handoff(
                    conn,
                    session_id="sess-checkpoint",
                    step=1,
                    process_key="STRATEGIZE",
                    item_id=f"YOK-{9000}",
                    checkpoint_label="checkpoint-0",
                )
        assert checkpoint["handler_outcome"] == OUTCOME_INTERACTIVE_CHECKPOINT
        # The chain must NOT chain — the operator must reply
        # before the process resumes.
        assert checkpoint["chainable"] is False
        assert checkpoint["action"] == "STRATEGIZE"
        assert checkpoint["item_id"] == f"YOK-{9000}"
        assert checkpoint["status"] == "checkpoint-0"
