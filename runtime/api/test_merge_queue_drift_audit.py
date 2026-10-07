"""Skipped merge comparisons record public item references in audit events."""

from types import SimpleNamespace
from yoke_core.domain import merge_queue_drift_gate as gate_mod
from yoke_core.domain.merge_queue_live_drift import (
    LiveDriftReport,
    DRIFT_SKIP_DECLARATION_MISSING,
)


class TestSkipObservability:
    def test_a_skipped_check_emits_its_machine_readable_reason(
        self,
        monkeypatch,
    ):
        report = LiveDriftReport(
            skip_reason=DRIFT_SKIP_DECLARATION_MISSING,
            skip_detail="no declaration",
        )
        monkeypatch.setattr(
            gate_mod,
            "drift_blocking_landing",
            lambda *a, **k: report,
        )
        seen = {}

        def dispatch(**kwargs):
            seen.update(kwargs)
            return SimpleNamespace(
                success=True,
                result={"emitted": True},
                error=None,
            )

        monkeypatch.setattr(gate_mod, "call_dispatcher", dispatch)
        result = gate_mod.drift_check_before_landing(
            "yoke",
            checkout="/repo",
            branch="main",
            public_ref="YOK-7",
        )

        assert result is report
        assert seen["function_id"] == "events.emit"
        assert seen["payload"]["name"] == "MergeQueueDriftCheckSkipped"
        assert seen["payload"]["item_ref"] == "YOK-7"
        assert seen["payload"]["context"]["skip_reason"] == (
            DRIFT_SKIP_DECLARATION_MISSING
        )

    def test_event_write_failure_warns_without_blocking(self, monkeypatch):
        report = LiveDriftReport(
            skip_reason=DRIFT_SKIP_DECLARATION_MISSING,
            skip_detail="no declaration",
        )
        monkeypatch.setattr(
            gate_mod,
            "drift_blocking_landing",
            lambda *a, **k: report,
        )
        monkeypatch.setattr(
            gate_mod,
            "call_dispatcher",
            lambda **kwargs: SimpleNamespace(
                success=True,
                result={"emitted": False, "reason": "ledger unavailable"},
                error=None,
            ),
        )

        result = gate_mod.drift_check_before_landing(
            "yoke",
            checkout="/repo",
            branch="main",
            public_ref="YOK-7",
        )

        assert result.drifted is False
        assert "ledger unavailable" in result.unreadable[-1]
