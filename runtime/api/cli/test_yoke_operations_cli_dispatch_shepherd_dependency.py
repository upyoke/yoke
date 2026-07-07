"""Dispatch tests for shepherd dependency authoring wrappers."""

from __future__ import annotations

import pytest

from runtime.api.cli.test_yoke_operations_cli_dispatch import (
    _CAPTURED_REQUESTS,
    _run_capture,
    _run_with_dispatch,
    _stub_dispatch_ok,
)


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CAPTURED_REQUESTS.clear()


class TestShepherdDependencyWriteDispatch:
    def test_dependency_add_dispatches_coordination_only(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "shepherd", "dependency-add",
            "YOK-20", "YOK-10", "idea",
            "--gate-point", "coordination_only",
            "--rationale", "shared paths are independent",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "shepherd.dependency_add.run"
        assert req.target.kind == "item"
        assert req.target.item_ref == "YOK-20"
        assert req.payload == {
            "blocking_item": "YOK-10",
            "source": "idea",
            "gate_point": "coordination_only",
            "rationale": "shared paths are independent",
            "evidence_json": "{}",
        }

    def test_dependency_add_dispatches_activation_fact_merged(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "shepherd", "dependency-add",
            "YOK-20", "YOK-10", "feed",
            "--gate-point", "activation",
            "--satisfaction", "fact:merged",
            "--rationale", "upstream lands schema first",
            "--evidence", '{"shared_files":["runtime/api/db.py"]}',
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "shepherd.dependency_add.run"
        assert req.payload == {
            "blocking_item": "YOK-10",
            "source": "feed",
            "gate_point": "activation",
            "rationale": "upstream lands schema first",
            "evidence_json": '{"shared_files":["runtime/api/db.py"]}',
            "satisfaction": "fact:merged",
        }

    def test_dependency_update_dispatches_fact_merged(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "shepherd", "dependency-update",
            "YOK-20", "YOK-10",
            "--match-gate-point", "activation",
            "--gate-point", "integration",
            "--satisfaction", "fact:merged",
            "--rationale", "merge order still matters",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "shepherd.dependency_update.run"
        assert req.target.item_ref == "YOK-20"
        assert req.payload == {
            "blocking_item": "YOK-10",
            "match_gate_point": "activation",
            "gate_point": "integration",
            "satisfaction": "fact:merged",
            "rationale": "merge order still matters",
        }

    def test_dependency_remove_dispatches(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "shepherd", "dependency-remove", "YOK-20", "YOK-10",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "shepherd.dependency_remove.run"
        assert req.target.item_ref == "YOK-20"
        assert req.payload == {"blocking_item": "YOK-10"}

    def test_dependency_add_help_lists_authoring_flags(self) -> None:
        rc, out, _err = _run_capture(
            _stub_dispatch_ok, "shepherd", "dependency-add", "--help",
        )
        assert rc == 0
        assert "yoke shepherd dependency-add" in out
        assert "--gate-point" in out
        assert "--satisfaction" in out
        assert "--rationale" in out


class TestShepherdVerdictWriteDispatch:
    def test_verdict_dispatches(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "shepherd", "verdict",
            "--item", "YOK-42",
            "--transition", "planning_to_plan_drafted",
            "--worker", "Worker F",
            "--verdict", "BLOCKED",
            "--caveats", "needs another pass",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "shepherd.verdict.run"
        assert req.target.kind == "item"
        assert req.target.item_ref == "YOK-42"
        assert req.payload == {
            "transition": "planning_to_plan_drafted",
            "worker": "Worker F",
            "verdict": "BLOCKED",
            "caveats": "needs another pass",
        }

    def test_caveat_disposition_dispatches(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "shepherd", "caveat-disposition",
            "--item", "YOK-42",
            "--transition", "planning_to_plan_drafted",
            "--attempt", "2",
            "--caveat-num", "1",
            "--caveat-text", "Needs QA waiver rationale",
            "--disposition", "RESOLVED",
            "--resolution-details", "Rationale recorded",
            "--verdict-id", "99",
        )
        assert rc == 0
        req = _CAPTURED_REQUESTS[-1]
        assert req.function == "shepherd.caveat_disposition.run"
        assert req.target.kind == "item"
        assert req.target.item_ref == "YOK-42"
        assert req.payload == {
            "transition": "planning_to_plan_drafted",
            "attempt": 2,
            "caveat_num": 1,
            "caveat_text": "Needs QA waiver rationale",
            "disposition": "RESOLVED",
            "resolution_details": "Rationale recorded",
            "verdict_id": 99,
        }

    def test_caveat_disposition_rejects_unknown_disposition(self) -> None:
        rc = _run_with_dispatch(
            _stub_dispatch_ok,
            "shepherd", "caveat-disposition",
            "--item", "YOK-42",
            "--transition", "planning_to_plan_drafted",
            "--attempt", "2",
            "--caveat-num", "1",
            "--caveat-text", "Needs QA waiver rationale",
            "--disposition", "UNKNOWN",
        )
        assert rc == 2
        assert _CAPTURED_REQUESTS == []
