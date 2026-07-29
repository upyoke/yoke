"""Compact operator-abort CLI coverage."""

from __future__ import annotations

import json
from unittest import mock

from yoke_core.domain import qa_plan_execution_abort_cli


def test_abort_prints_compact_receipt(capsys) -> None:
    response = {
        "execution_id": "execution-1",
        "item_id": None,
        "deployment_run_id": "run-1",
        "transition_id": None,
        "state": "aborted",
        "cursor_ordinal": 3,
        "machine_lease_id": None,
        "requirements": [{"large": "roster"}],
        "results": [{"large": "results"}],
    }
    with (
        mock.patch.object(
            qa_plan_execution_abort_cli,
            "_call_plan_function",
            return_value=response,
        ) as call,
        mock.patch(
            "yoke_core.api.service_client_structured_api_adapter.build_actor",
            return_value="actor",
        ),
    ):
        exit_code = qa_plan_execution_abort_cli.run(
            [
                "--deployment-run-id",
                "run-1",
                "--execution-id",
                "execution-1",
                "--reason",
                "operator-interrupt",
                "--project",
                "yoke",
            ]
        )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {
        "cursor_ordinal": 3,
        "deployment_run_id": "run-1",
        "execution_id": "execution-1",
        "item_id": None,
        "machine_lease_id": None,
        "state": "aborted",
        "transition_id": None,
    }
    assert call.call_args.kwargs["function_id"] == "qa.plan_execution.abort"
    assert call.call_args.kwargs["payload"] == {
        "execution_id": "execution-1",
        "reason": "operator-interrupt",
    }
    assert call.call_args.kwargs["target"].deployment_run_id == "run-1"
