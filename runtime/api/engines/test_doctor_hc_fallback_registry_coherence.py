"""Tests for HC-fallback-registry-coherence."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from yoke_core.engines.doctor_hc_fallback_registry_coherence import (
    hc_fallback_registry_coherence,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


def _run() -> RecordCollector:
    rec = RecordCollector()
    args = DoctorArgs()
    hc_fallback_registry_coherence(None, args, rec)
    return rec


class TestHcFallbackRegistryCoherence:
    def test_passes_against_live_registries(self) -> None:
        rec = _run()
        assert len(rec.results) == 1
        result = rec.results[0]
        assert result.result == "PASS", (
            f"unexpected FAIL detail: {result.detail}"
        )
        assert "wrapped" in result.detail
        assert "pending" in result.detail

    def test_self_skips_when_tracker_missing(self) -> None:
        with patch(
            "yoke_core.engines.doctor_hc_fallback_registry_coherence._resolve_tracker",
            return_value=None,
        ):
            rec = _run()
        assert rec.results[0].result == "PASS"
        assert "self-skipped" in rec.results[0].detail

    def test_fails_when_wrapped_row_not_in_subcommand_registry(self) -> None:
        from yoke_cli import operation_inventory as inv

        bogus = inv.OperationEntry(
            shell_form="yoke made up subcommand",
            family="bogus",
            status=inv.WRAPPED,
            reason=inv.REASON_WRAPPED_BY_YOKE_CLI,
        )
        _original = inv.by_status

        def patched(status):
            if status == inv.WRAPPED:
                return [bogus]
            return _original(status)

        with patch.object(inv, "by_status", side_effect=patched):
            rec = _run()
        assert rec.results[0].result == "FAIL"
        assert "made up" in rec.results[0].detail

    def test_fails_when_pending_row_lacks_multi_module_shape(self) -> None:
        from yoke_cli import operation_inventory as inv

        bogus = inv.OperationEntry(
            shell_form="not a multi-module shape",
            family="bogus",
            status=inv.PENDING,
            reason=inv.REASON_NO_HANDLER_REGISTERED,
            proposed_function_id="bogus.fn.run",
        )
        _original = inv.by_status

        def patched(status):
            if status == inv.PENDING:
                return [bogus]
            return _original(status)

        with patch.object(inv, "by_status", side_effect=patched):
            rec = _run()
        assert rec.results[0].result == "FAIL"
        assert "not a multi-module" in rec.results[0].detail
