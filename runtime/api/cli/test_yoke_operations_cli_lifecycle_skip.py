"""Tests for the lifecycle skip CLI adapter."""

from __future__ import annotations

import io
from contextlib import redirect_stderr
from unittest.mock import patch

from yoke_cli.commands import flag_adapters as adapters
from yoke_cli.main import main as cli_main
from yoke_cli.commands.registry import resolve


class TestLifecycleSkipRecordRecoverableSubstrate:
    """The wrapped surface that makes /yoke do Step B executable."""

    def test_token_tuple_resolves_to_function_id(self) -> None:
        cli_tokens, function_id, _, remaining = resolve(
            ["lifecycle", "skip", "record-recoverable-substrate", "YOK-1849"]
        )
        assert cli_tokens == (
            "lifecycle", "skip", "record-recoverable-substrate",
        )
        assert function_id == "lifecycle.skip.record_recoverable_substrate"
        assert remaining == ["YOK-1849"]

    def test_flag_adapter_parses_all_seven_flags(self) -> None:
        captured: dict = {}

        def _fake_dispatch(*, function_id, target, payload,
                           session_id, json_mode):
            captured["function_id"] = function_id
            captured["target"] = target
            captured["payload"] = payload
            captured["session_id"] = session_id
            captured["json_mode"] = json_mode
            return 0

        with patch(
            "yoke_cli.commands.adapters.items.dispatch_and_emit",
            side_effect=_fake_dispatch,
        ):
            rc = adapters.lifecycle_skip_record_recoverable_substrate(
                [
                    "1849",
                    "--chain-step", "2",
                    "--project", "yoke",
                    "--routed-action", "advance",
                    "--failure-class", "cwd_drift",
                    "--remediation-owner", "YOK-1862",
                    "--current-status", "implementing",
                    "--useful-work-began",
                ]
            )
        assert rc == 0
        assert captured["function_id"] == (
            "lifecycle.skip.record_recoverable_substrate"
        )
        assert captured["target"].kind == "item"
        assert captured["target"].item_ref == "1849"
        assert captured["payload"] == {
            "chain_step": 2,
            "project": "yoke",
            "routed_action": "advance",
            "failure_class": "cwd_drift",
            "remediation_owner": "YOK-1862",
            "useful_work_began": True,
            "current_status": "implementing",
        }

    def test_current_status_optional_and_useful_work_default_false(
        self,
    ) -> None:
        captured: dict = {}

        def _fake_dispatch(*, function_id, target, payload,
                           session_id, json_mode):
            captured.update(payload)
            return 0

        with patch(
            "yoke_cli.commands.adapters.items.dispatch_and_emit",
            side_effect=_fake_dispatch,
        ):
            rc = adapters.lifecycle_skip_record_recoverable_substrate(
                [
                    "1849",
                    "--chain-step", "1",
                    "--project", "yoke",
                    "--routed-action", "advance",
                    "--failure-class", "lease-conflict",
                    "--remediation-owner", "YOK-1862",
                ]
            )
        assert rc == 0
        assert captured["useful_work_began"] is False
        assert "current_status" not in captured

    def test_missing_required_flag_returns_usage_error(self) -> None:
        err = io.StringIO()
        with redirect_stderr(err):
            rc = adapters.lifecycle_skip_record_recoverable_substrate(
                ["1849"]
            )
        assert rc == 2

    def test_end_to_end_cli_main_dispatch_envelope(self) -> None:
        captured: dict = {}

        def _fake_dispatch(*, function_id, target, payload,
                           session_id, json_mode):
            captured["function_id"] = function_id
            captured["target_kind"] = target.kind
            captured["item_ref"] = target.item_ref
            captured["payload"] = payload
            return 0

        with patch(
            "yoke_cli.commands.adapters.items.dispatch_and_emit",
            side_effect=_fake_dispatch,
        ):
            rc = cli_main(
                [
                    "lifecycle", "skip", "record-recoverable-substrate",
                    "1849",
                    "--chain-step", "2",
                    "--project", "yoke",
                    "--routed-action", "advance",
                    "--failure-class", "cwd_drift",
                    "--remediation-owner", "YOK-1862",
                ]
            )
        assert rc == 0
        assert captured["function_id"] == (
            "lifecycle.skip.record_recoverable_substrate"
        )
        assert captured["target_kind"] == "item"
        assert captured["item_ref"] == "1849"
        assert captured["payload"]["chain_step"] == 2
        assert captured["payload"]["failure_class"] == "cwd_drift"
