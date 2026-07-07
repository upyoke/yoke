"""Handler coverage for shepherd.dependency_list.run."""

from __future__ import annotations

from yoke_core.domain.handlers import (
    shepherd_dependency_writes,
    shepherd_reads,
    shepherd_verdict_writes,
)
from yoke_core.domain.shepherd_dependency import cmd_dependency_add
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


def _request(target: TargetRef) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="shepherd.dependency_list.run",
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


class TestShepherdDependencyList:
    def test_rejects_non_item_target(self):
        outcome = shepherd_reads.handle_shepherd_dependency_list(
            _request(TargetRef(kind="global"))
        )
        assert not outcome.primary_success
        assert outcome.error.code == "target_invalid"

    def test_lists_both_directions(self, test_db):
        # 10 depends on 5; 20 depends on 10 — so for item 10 we expect one
        # 'depends-on' row (other=5) and one 'blocks' row (other=20).
        cmd_dependency_add(test_db, "YOK-10", "YOK-5", "operator")
        cmd_dependency_add(test_db, "YOK-20", "YOK-10", "operator")
        test_db.commit()
        outcome = shepherd_reads.handle_shepherd_dependency_list(
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
        outcome = shepherd_reads.handle_shepherd_dependency_list(
            _request(TargetRef(kind="item", item_id=77))
        )
        assert outcome.primary_success
        assert outcome.result_payload["dependencies"] == []


class TestShepherdDependencyWrites:
    def test_add_update_remove_round_trip(self, test_db):
        add_outcome = shepherd_dependency_writes.handle_shepherd_dependency_add(
            _write_request(
                "shepherd.dependency_add.run",
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

        update_outcome = shepherd_dependency_writes.handle_shepherd_dependency_update(
            _write_request(
                "shepherd.dependency_update.run",
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

        rows = shepherd_reads.handle_shepherd_dependency_list(
            _request(TargetRef(kind="item", item_id=30))
        ).result_payload["dependencies"]
        assert rows[0]["gate_point"] == "activation"
        assert rows[0]["satisfaction"] == "fact:merged"

        remove_outcome = shepherd_dependency_writes.handle_shepherd_dependency_remove(
            _write_request(
                "shepherd.dependency_remove.run",
                TargetRef(kind="item", item_id=30),
                {"blocking_item": "YOK-10"},
            )
        )
        assert remove_outcome.primary_success
        rows = shepherd_reads.handle_shepherd_dependency_list(
            _request(TargetRef(kind="item", item_id=30))
        ).result_payload["dependencies"]
        assert rows == []

    def test_add_rejects_non_item_target(self):
        outcome = shepherd_dependency_writes.handle_shepherd_dependency_add(
            _write_request(
                "shepherd.dependency_add.run",
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
            "WHERE item = %s AND transition = %s AND attempt = %s "
            "AND caveat_num = %s",
            ("YOK-42", "planning_to_plan_drafted", 1, 1),
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
