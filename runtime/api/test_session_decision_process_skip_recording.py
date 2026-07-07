"""Disabled-process chain-skip-memory recording regressions.

Sibling of :mod:`runtime.api.test_session_decision_process_gate`. Covers
When the gate filters a disabled process action,
``record_disabled_process_skip`` persists the skip in the per-session
chain-skip memory and emits a ``SchedulerOfferSkipped`` audit event so
the next offer in the same chain dedupes the disabled process.

The gate proper is a pure function and is covered in the gate test
module; this module focuses on the recording side-effect that needs a
live read-write SQLite connection.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain.session_contract import ActionKind, NextAction
from yoke_core.domain.session_decision_process_gate import (
    merge_skip_memory_with_policy,
    record_disabled_process_skip,
)
from yoke_core.domain.sessions_queries_chain import read_chain_skip_memory
from yoke_core.api.routing_config import ProcessOfferPolicy
from runtime.api.test_sessions import _register, conn  # noqa: F401  (Postgres-backed pytest fixture)


def _capture():
    captured: list[dict] = []
    return captured, patch(
        "yoke_core.domain.events.emit_event",
        side_effect=lambda name, **kw: captured.append({"name": name, **kw}),
    )


class TestRecordDisabledProcessSkip:
    """AC-19 / AC-42 / AC-45: persist chain-skip + emit SchedulerOfferSkipped."""

    def test_records_skip_when_charge_swap_payload_present(self, conn):
        _register(conn, session_id="rec-charge")
        action = NextAction(
            action=ActionKind.CHARGE,
            reason="swap to runnable",
            chainable=True,
            correlation_id="rec-charge",
            context={
                "selected_item": f"YOK-{1605}",
                "runnable_items": [f"YOK-{1605}"],
                "skipped_process": {
                    "process_key": "STRATEGIZE",
                    "config_key": "do_process_offer_strategize",
                    "recommended_action": "strategize",
                    "skip_reason": "process_disabled_by_config",
                    "direct_command": "/yoke strategize",
                },
            },
        )
        captured, ctx_mgr = _capture()
        with ctx_mgr:
            recorded = record_disabled_process_skip(
                conn,
                session_id="rec-charge",
                chain_step=3,
                project="yoke",
                action=action,
            )
        assert recorded is True
        memory = read_chain_skip_memory(conn, "rec-charge")
        assert len(memory) == 1
        assert memory[0]["process_key"] == "STRATEGIZE"
        assert memory[0]["skip_reason"] == "process_disabled_by_config"
        assert memory[0]["chain_step"] == 3
        assert memory[0]["config_key"] == "do_process_offer_strategize"
        events = [c for c in captured if c["name"] == "SchedulerOfferSkipped"]
        assert len(events) == 1
        ctx = events[0]["context"]
        assert ctx["session_id"] == "rec-charge"
        assert ctx["skip_reason"] == "process_disabled_by_config"
        assert ctx["process_key"] == "STRATEGIZE"
        assert ctx["config_key"] == "do_process_offer_strategize"
        assert ctx["recommended_action"] == "strategize"
        assert ctx["chain_step"] == 3

    def test_records_skip_when_suppressed_wait_payload_present(self, conn):
        _register(conn, session_id="rec-wait")
        action = NextAction(
            action=ActionKind.WAIT,
            reason="STRATEGIZE recommended but disabled by do_process_offer_strategize=false",
            chainable=False,
            correlation_id="rec-wait",
            context={
                "wait_reason": "process_suppressed_no_alternative",
                "suppressed_process_recommendation": {
                    "process_key": "STRATEGIZE",
                    "config_key": "do_process_offer_strategize",
                    "recommended_action": "strategize",
                    "direct_command": "/yoke strategize",
                    "skip_reason": "process_disabled_by_config",
                    "original_reason": "Drift review: SML impacted.",
                    "original_context": {"trigger": "drift_review"},
                },
            },
        )
        captured, ctx_mgr = _capture()
        with ctx_mgr:
            recorded = record_disabled_process_skip(
                conn,
                session_id="rec-wait",
                chain_step=2,
                project="yoke",
                action=action,
            )
        assert recorded is True
        memory = read_chain_skip_memory(conn, "rec-wait")
        assert len(memory) == 1
        assert memory[0]["process_key"] == "STRATEGIZE"
        assert memory[0]["skip_reason"] == "process_disabled_by_config"

    def test_no_op_for_non_process_action(self, conn):
        _register(conn, session_id="rec-noop")
        action = NextAction(
            action=ActionKind.CHARGE,
            reason="normal charge",
            chainable=True,
            correlation_id="rec-noop",
            context={"selected_item": f"YOK-{1700}", "runnable_items": [f"YOK-{1700}"]},
        )
        captured, ctx_mgr = _capture()
        with ctx_mgr:
            recorded = record_disabled_process_skip(
                conn,
                session_id="rec-noop",
                chain_step=1,
                project="yoke",
                action=action,
            )
        assert recorded is False
        assert read_chain_skip_memory(conn, "rec-noop") == []
        assert [c for c in captured if c["name"] == "SchedulerOfferSkipped"] == []

    def test_no_op_when_action_lacks_process_payload(self, conn):
        _register(conn, session_id="rec-empty")
        action = NextAction(
            action=ActionKind.WAIT,
            reason="no work",
            chainable=False,
            correlation_id="rec-empty",
        )
        captured, ctx_mgr = _capture()
        with ctx_mgr:
            recorded = record_disabled_process_skip(
                conn,
                session_id="rec-empty",
                chain_step=1,
                project="yoke",
                action=action,
            )
        assert recorded is False
        assert read_chain_skip_memory(conn, "rec-empty") == []


class TestMergeSkipMemoryWithPolicy:
    """AC-5: chain_skip_memory.process_key entries disable the matching key."""

    def test_no_memory_returns_policy_unchanged(self):
        policy = ProcessOfferPolicy(per_process={"feed": True})
        merged = merge_skip_memory_with_policy(policy, None)
        assert merged is policy
        merged_empty = merge_skip_memory_with_policy(policy, [])
        assert merged_empty is policy

    def test_process_key_entry_disables_in_merged_policy(self):
        policy = ProcessOfferPolicy(per_process={"feed": True, "strategize": True})
        memory = [
            {"process_key": "FEED", "skip_reason": "process_disabled_by_config"},
        ]
        merged = merge_skip_memory_with_policy(policy, memory)
        assert merged is not None
        assert merged.is_enabled("FEED") is False
        # Strategize remains enabled — only the named key is suppressed.
        assert merged.is_enabled("STRATEGIZE") is True

    def test_item_id_only_entries_leave_policy_untouched(self):
        # Item-id entries are handled by the existing item-id filter;
        # the policy merge only fires on entries with process_key set.
        policy = ProcessOfferPolicy(per_process={"feed": True})
        memory = [{"item_id": "YOK-42"}]
        merged = merge_skip_memory_with_policy(policy, memory)
        assert merged is policy

    def test_none_policy_with_process_key_entry_yields_disabled_policy(self):
        memory = [{"process_key": "FEED"}]
        merged = merge_skip_memory_with_policy(None, memory)
        assert merged is not None
        assert merged.is_enabled("FEED") is False
