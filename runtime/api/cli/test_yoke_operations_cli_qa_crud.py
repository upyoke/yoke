"""Dispatch-path tests for the qa CRUD conversion slice —
``yoke qa requirement list/get/add/add-batch``, ``yoke qa run list``,
``yoke qa run get``, ``yoke qa gate-summary``."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from typing import List
from unittest.mock import patch

import pytest

from yoke_cli.main import main as cli_main
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
)


_CAPTURED_REQUESTS: List[FunctionCallRequest] = []


def _stub_ok(request: FunctionCallRequest) -> FunctionCallResponse:
    _CAPTURED_REQUESTS.append(request)
    return FunctionCallResponse(
        success=True, function=request.function, version=request.version,
        request_id=request.request_id, result={"echo": True},
    )


def _stub_fail(request: FunctionCallRequest) -> FunctionCallResponse:
    _CAPTURED_REQUESTS.append(request)
    return FunctionCallResponse(
        success=False, function=request.function, version=request.version,
        request_id=request.request_id,
        error=FunctionError(code="claim_required", message="stub"),
    )


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


def _run(stub, *argv: str, stdin: str = "") -> int:
    with patch.dict("os.environ", {"YOKE_SESSION_ID": "test-session"}):
        with patch(
            "yoke_core.domain.yoke_function_dispatch.dispatch",
            side_effect=stub,
        ):
            with patch(
                "yoke_cli.commands._helpers.ensure_handlers_loaded"
            ):
                with patch("sys.stdin", io.StringIO(stdin)):
                    with redirect_stdout(io.StringIO()), \
                            redirect_stderr(io.StringIO()):
                        return cli_main(list(argv))


class TestQaRequirementList:
    def test_item_filter_rides_target(self) -> None:
        rc = _run(_stub_ok, "qa", "requirement", "list", "--item", "1833")
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "qa.requirement.list"
        assert req.target.kind == "item"
        assert req.target.item_ref == "1833"
        assert req.payload == {}

    def test_epic_filter_rides_payload(self) -> None:
        rc = _run(_stub_ok, "qa", "requirement", "list", "--epic-id", "1704")
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.target.kind == "global"
        assert req.payload == {"epic_id": 1704}

    def test_no_filter_is_global(self) -> None:
        rc = _run(_stub_ok, "qa", "requirement", "list")
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.target.kind == "global"
        assert req.payload == {}


class TestQaRequirementGet:
    def test_dispatches_requirement_target(self) -> None:
        rc = _run(
            _stub_ok, "qa", "requirement", "get", "--requirement-id", "5731",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "qa.requirement.get"
        assert req.target.kind == "qa_requirement"
        assert req.target.qa_requirement_id == 5731

    def test_missing_id_returns_two(self) -> None:
        rc = _run(_stub_ok, "qa", "requirement", "get")
        assert rc == 2
        assert _CAPTURED_REQUESTS == []


class TestQaRequirementAdd:
    def test_dispatches_full_payload(self) -> None:
        rc = _run(
            _stub_ok, "qa", "requirement", "add", "--item", "1833",
            "--qa-kind", "ac_verification", "--qa-phase", "verification",
            "--requirement-source", "ac_derived",
            "--success-policy", "AC-1 verified",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "qa.requirement.add"
        assert req.target.kind == "item"
        assert req.target.item_ref == "1833"
        assert req.payload == {
            "qa_kind": "ac_verification", "qa_phase": "verification",
            "blocking_mode": "blocking", "requirement_source": "ac_derived",
            "success_policy": "AC-1 verified",
        }

    def test_missing_required_flags_return_two(self) -> None:
        rc = _run(_stub_ok, "qa", "requirement", "add", "--item", "1833")
        assert rc == 2
        assert _CAPTURED_REQUESTS == []

    def test_claim_denial_propagates_exit_one(self) -> None:
        rc = _run(
            _stub_fail, "qa", "requirement", "add", "--item", "1833",
            "--qa-kind", "ac_verification", "--qa-phase", "verification",
        )
        assert rc == 1


class TestQaRequirementAddBatch:
    def test_stdin_rows_dispatch(self) -> None:
        rows = [{"qa_kind": "ac_verification", "qa_phase": "verification"}]
        rc = _run(
            _stub_ok, "qa", "requirement", "add-batch", "--item", "1833",
            "--stdin", stdin=json.dumps(rows),
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "qa.requirement.add_batch"
        assert req.target.item_ref == "1833"
        assert req.payload == {"rows": rows}

    def test_rows_file_dispatch(self, tmp_path) -> None:
        rows = [{"qa_kind": "ac_verification", "qa_phase": "verification"}]
        rows_file = tmp_path / "rows.json"
        rows_file.write_text(json.dumps(rows), encoding="utf-8")
        rc = _run(
            _stub_ok, "qa", "requirement", "add-batch", "--item", "1833",
            "--rows-file", str(rows_file),
        )
        assert rc == 0
        assert _CAPTURED_REQUESTS[-1].payload == {"rows": rows}

    def test_invalid_json_returns_two(self) -> None:
        rc = _run(
            _stub_ok, "qa", "requirement", "add-batch", "--item", "1833",
            "--stdin", stdin="not json",
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []

    def test_non_array_returns_two(self) -> None:
        rc = _run(
            _stub_ok, "qa", "requirement", "add-batch", "--item", "1833",
            "--stdin", stdin='{"qa_kind": "x"}',
        )
        assert rc == 2

    def test_missing_source_selector_returns_two(self) -> None:
        rc = _run(
            _stub_ok, "qa", "requirement", "add-batch", "--item", "1833",
        )
        assert rc == 2


class TestQaRunList:
    def test_requirement_target(self) -> None:
        rc = _run(_stub_ok, "qa", "run", "list", "--requirement-id", "5731")
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "qa.run.list"
        assert req.target.kind == "qa_requirement"
        assert req.target.qa_requirement_id == 5731

    def test_unfiltered_global(self) -> None:
        rc = _run(_stub_ok, "qa", "run", "list")
        assert rc == 0
        assert _CAPTURED_REQUESTS[-1].target.kind == "global"


class TestQaRunGet:
    def test_dispatches_run_id_payload(self) -> None:
        rc = _run(_stub_ok, "qa", "run", "get", "--run-id", "8142")
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "qa.run.get"
        assert req.target.kind == "global"
        assert req.payload == {"run_id": 8142}

    def test_missing_run_id_returns_two(self) -> None:
        rc = _run(_stub_ok, "qa", "run", "get")
        assert rc == 2
        assert _CAPTURED_REQUESTS == []


class TestQaGateSummary:
    def test_item_target_with_transition_payload(self) -> None:
        rc = _run(
            _stub_ok, "qa", "gate-summary", "--item", "1833",
            "--target", "reviewed-implementation",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "qa.gate_summary.run"
        assert req.target.kind == "item"
        assert req.target.item_ref == "1833"
        assert req.payload == {"transition": "reviewed-implementation"}

    def test_epic_task_target(self) -> None:
        rc = _run(
            _stub_ok, "qa", "gate-summary", "--epic-id", "1704",
            "--task-num", "5", "--target", "implemented",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.target.kind == "epic_task"
        assert req.target.epic_id == 1704
        assert req.target.task_num == 5
        assert req.payload == {"transition": "implemented"}

    def test_invalid_target_choice_returns_two(self) -> None:
        rc = _run(
            _stub_ok, "qa", "gate-summary", "--item", "1833",
            "--target", "done",
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []

    def test_missing_target_shape_returns_two(self) -> None:
        rc = _run(
            _stub_ok, "qa", "gate-summary",
            "--target", "implemented",
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
