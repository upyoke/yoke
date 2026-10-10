"""Handler coverage for items.dependency.list."""

from __future__ import annotations

import pytest

from yoke_core.domain.handlers import (
    item_dependency_reads,
    item_dependency_writes,
    shepherd_verdict_writes,
)
from runtime.api.conftest import insert_item
from yoke_core.domain.item_dependency import cmd_dependency_add
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


_FIXTURE_ITEM_REF = f"YOK-{42}"


def _request(target: TargetRef) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="items.dependency.list",
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=target,
        payload={},
    )


def _write_request(
    function_id: str,
    target: TargetRef,
    payload: dict,
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=target,
        payload=payload,
    )


class TestItemDependencyList:
    def test_rejects_non_item_target(self):
        outcome = item_dependency_reads.handle_item_dependency_list(
            _request(TargetRef(kind="global"))
        )
        assert not outcome.primary_success
        assert outcome.error.code == "target_invalid"

    def test_lists_both_directions(self, test_db):
        # 10 depends on 5; 20 depends on 10 — so for item 10 we expect one
        # 'depends-on' row (other=5) and one 'blocks' row (other=20).
        for item_id in (5, 10, 20):
            insert_item(test_db, id=item_id, title=f"item {item_id}")
        cmd_dependency_add(test_db, "YOK-10", "YOK-5", "operator")
        cmd_dependency_add(test_db, "YOK-20", "YOK-10", "operator")
        test_db.commit()
        outcome = item_dependency_reads.handle_item_dependency_list(
            _request(TargetRef(kind="item", item_id=10))
        )
        assert outcome.primary_success
        assert outcome.result_payload["item_id"] == 10
        rows = outcome.result_payload["dependencies"]
        by_direction = {row["direction"]: row for row in rows}
        assert by_direction["depends-on"]["other_item"] == "YOK-5"
        assert by_direction["blocks"]["other_item"] == "YOK-20"
        assert by_direction["depends-on"]["gate_point"] == "activation"

    def test_empty_graph_returns_no_rows(self, test_db):
        insert_item(test_db, id=77)
        test_db.commit()
        outcome = item_dependency_reads.handle_item_dependency_list(
            _request(TargetRef(kind="item", item_id=77))
        )
        assert outcome.primary_success
        assert outcome.result_payload["dependencies"] == []
        assert outcome.result_payload["integration_gate"] == {
            "evaluated": True,
            "is_blocked": False,
            "blockers": [],
        }

    @pytest.mark.parametrize(
        ("gate_point", "reverse", "merged", "blocked"),
        [
            ("integration", False, False, True),
            ("integration", False, True, False),
            ("integration", True, False, False),
            ("coordination_only", False, False, False),
            ("activation", False, False, False),
        ],
    )
    def test_integration_gate_uses_direction_and_satisfaction(
        self,
        test_db,
        gate_point,
        reverse,
        merged,
        blocked,
    ):
        subject, other = 10, 20
        subject_ref, other_ref = f"YOK-{subject}", f"YOK-{other}"
        for item_id in (subject, other):
            insert_item(test_db, id=item_id, title=f"item {item_id}")
        dependent, blocking = (
            (other_ref, subject_ref) if reverse else (subject_ref, other_ref)
        )
        cmd_dependency_add(
            test_db,
            dependent,
            blocking,
            "operator",
            gate_point=gate_point,
            satisfaction=None if gate_point == "coordination_only" else "fact:merged",
            rationale="independent edits" if gate_point == "coordination_only" else "",
        )
        if merged:
            test_db.execute(
                "UPDATE items SET merged_at = %s WHERE id = %s",
                ("2026-01-01T00:00:00Z", other),
            )
        test_db.commit()
        outcome = item_dependency_reads.handle_item_dependency_list(
            _request(TargetRef(kind="item", item_id=subject))
        )
        assert outcome.primary_success
        assert len(outcome.result_payload["dependencies"]) == 1
        gate = outcome.result_payload["integration_gate"]
        assert gate["evaluated"] is True
        assert gate["is_blocked"] is blocked
        if blocked:
            assert len(gate["blockers"]) == 1
            assert gate["blockers"][0]["public_ref"] == other_ref
            assert gate["blockers"][0]["reason"]
        else:
            assert gate["blockers"] == []

    def test_evaluation_failure_preserves_edges_without_exception_text(
        self,
        test_db,
        monkeypatch,
    ):
        from yoke_core.domain import dependency_planning

        subject, other = 10, 20
        for item_id in (subject, other):
            insert_item(test_db, id=item_id)
        cmd_dependency_add(test_db, f"YOK-{subject}", f"YOK-{other}", "operator")
        test_db.commit()

        def fail(conn, public_ref, gate_point):
            assert conn is not None
            assert public_ref == f"YOK-{subject}"
            assert gate_point == "integration"
            raise RuntimeError("private exception details")

        monkeypatch.setattr(dependency_planning, "evaluate_item_gate", fail)
        outcome = item_dependency_reads.handle_item_dependency_list(
            _request(TargetRef(kind="item", item_id=subject))
        )
        assert outcome.primary_success
        assert len(outcome.result_payload["dependencies"]) == 1
        assert outcome.result_payload["integration_gate"] == {
            "evaluated": False,
            "is_blocked": None,
            "error_code": "integration_dependency_evaluation_failed",
        }
        assert "private exception details" not in str(outcome.result_payload)


class TestItemDependencyWrites:
    def test_add_update_remove_round_trip(self, test_db):
        for item_id in (10, 30):
            insert_item(test_db, id=item_id, title=f"item {item_id}")
        add_outcome = item_dependency_writes.handle_item_dependency_add(
            _write_request(
                "items.dependency.add",
                TargetRef(kind="item", item_id=30),
                {
                    "blocking_item": "YOK-10",
                    "source": "idea",
                    "gate_point": "coordination_only",
                    "rationale": "shared file edits are independent",
                },
            )
        )
        assert add_outcome.primary_success
        assert add_outcome.result_payload["dependent_item"] == "YOK-30"

        update_outcome = item_dependency_writes.handle_item_dependency_update(
            _write_request(
                "items.dependency.update",
                TargetRef(kind="item", item_id=30),
                {
                    "blocking_item": "YOK-10",
                    "match_gate_point": "coordination_only",
                    "gate_point": "activation",
                    "satisfaction": "fact:merged",
                    "rationale": "upstream lands first",
                },
            )
        )
        assert update_outcome.primary_success

        rows = item_dependency_reads.handle_item_dependency_list(
            _request(TargetRef(kind="item", item_id=30))
        ).result_payload["dependencies"]
        assert rows[0]["gate_point"] == "activation"
        assert rows[0]["satisfaction"] == "fact:merged"

        remove_outcome = item_dependency_writes.handle_item_dependency_remove(
            _write_request(
                "items.dependency.remove",
                TargetRef(kind="item", item_id=30),
                {"blocking_item": "YOK-10"},
            )
        )
        assert remove_outcome.primary_success
        rows = item_dependency_reads.handle_item_dependency_list(
            _request(TargetRef(kind="item", item_id=30))
        ).result_payload["dependencies"]
        assert rows == []

    def test_add_rejects_non_item_target(self):
        outcome = item_dependency_writes.handle_item_dependency_add(
            _write_request(
                "items.dependency.add",
                TargetRef(kind="global"),
                {
                    "blocking_item": "YOK-10",
                    "source": "idea",
                    "gate_point": "coordination_only",
                    "rationale": "shared file edits are independent",
                },
            )
        )
        assert not outcome.primary_success
        assert outcome.error.code == "target_invalid"


class TestShepherdVerdictWrites:
    def test_verdict_and_caveat_disposition_round_trip(self, test_db):
        insert_item(test_db, id=42)
        test_db.commit()
        verdict_outcome = shepherd_verdict_writes.handle_shepherd_verdict(
            _write_request(
                "shepherd.verdict.run",
                TargetRef(kind="item", item_id=42),
                {
                    "transition": "planning_to_plan_drafted",
                    "worker": "Worker F",
                    "verdict": "CAVEATS",
                    "caveats": "Needs QA waiver rationale",
                },
            )
        )
        assert verdict_outcome.primary_success
        verdict_id = verdict_outcome.result_payload["verdict_id"]

        disposition_outcome = (
            shepherd_verdict_writes.handle_shepherd_caveat_disposition(
                _write_request(
                    "shepherd.caveat_disposition.run",
                    TargetRef(kind="item", item_id=42),
                    {
                        "transition": "planning_to_plan_drafted",
                        "attempt": 1,
                        "caveat_num": 1,
                        "caveat_text": "Needs QA waiver rationale",
                        "disposition": "RESOLVED",
                        "resolution_details": "Waiver recorded",
                        "verdict_id": verdict_id,
                    },
                )
            )
        )
        assert disposition_outcome.primary_success

        row = test_db.execute(
            "SELECT disposition, resolution_details FROM caveat_dispositions "
            "WHERE public_ref = %s AND transition = %s AND attempt = %s "
            "AND caveat_num = %s",
            (_FIXTURE_ITEM_REF, "planning_to_plan_drafted", 1, 1),
        ).fetchone()
        assert row is not None
        assert row["disposition"] == "RESOLVED"
        assert row["resolution_details"] == "Waiver recorded"

    def test_verdict_rejects_non_item_target(self):
        outcome = shepherd_verdict_writes.handle_shepherd_verdict(
            _write_request(
                "shepherd.verdict.run",
                TargetRef(kind="global"),
                {
                    "transition": "planning_to_plan_drafted",
                    "worker": "Worker F",
                    "verdict": "READY",
                },
            )
        )
        assert not outcome.primary_success
        assert outcome.error.code == "target_invalid"
