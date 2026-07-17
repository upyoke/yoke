"""Tests for the ``frontier.list`` read handler and its domain read.

Real-DB coverage on the ``test_db`` fixture: the project-optional
all-scope default, engine-ranked ready rows with routed next-step verbs
and server-composed readiness prose, blocked rows across all three gate
points (activation from the frontier result; integration and closure
from the shared gate kernel, which the frontier computation does not
enforce), event-free reads, registration, and the browser allowlist.
"""

from __future__ import annotations

from datetime import datetime, timezone

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.frontier_list_read import (
    FRONTIER_BLOCKED_FIELDS,
    FRONTIER_READY_FIELDS,
    list_frontier,
)
from yoke_core.domain.handlers.frontier_list import handle_frontier_list

from runtime.api.fixtures.backlog import insert_item


def _iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _request(payload: dict | None = None) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="frontier.list",
        actor=ActorContext(actor_id=None, session_id=""),
        target=TargetRef(kind="global"),
        payload=payload or {},
    )


def _insert_dependency(
    conn,
    *,
    dependent_item: str,
    blocking_item: str,
    gate_point: str,
    rationale: str,
) -> None:
    conn.execute(
        "INSERT INTO item_dependencies ("
        "dependent_item, blocking_item, gate_point, satisfaction, "
        "source, rationale, created_at"
        ") VALUES (%s, %s, %s, 'status:done', 'test', %s, %s)",
        (dependent_item, blocking_item, gate_point, rationale, _iso()),
    )
    conn.commit()


def _event_count(conn) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])


class TestReadyRows:
    def test_ready_rows_carry_engine_rank_next_step_and_why_ready(
        self, test_db,
    ):
        insert_item(
            test_db, id=11, title="in flight", type="issue",
            status="implementing", priority="high",
        )
        result = list_frontier()
        assert result["fields"]["ready"] == list(FRONTIER_READY_FIELDS)
        assert result["fields"]["blocked"] == list(FRONTIER_BLOCKED_FIELDS)

        rows = result["ready_rows"]
        assert [row["item_id"] for row in rows] == ["YOK-11"]
        row = rows[0]
        # The rank is the engine's own zero-based ranking, in order.
        assert [r["rank"] for r in rows] == list(range(len(rows)))
        # An implementing issue routes to /yoke advance, and the command
        # cell is exactly the copy-paste invocation.
        assert row["next_step"] == "advance"
        assert row["run_command"] == "yoke advance YOK-11"
        assert row["item_type"] == "issue"
        assert row["project"] == "yoke"
        assert row["status"] == "implementing"
        # Readiness prose is composed server-side from computed facts.
        assert "no unsatisfied activation gates" in row["why_ready"].lower()
        assert "unclaimed" in row["why_ready"]
        assert result["wip_cap"] == 5
        assert result["wip_active"] == 1
        assert result["frozen_count"] == 0

    def test_unblocking_leverage_reaches_the_prose(self, test_db):
        insert_item(
            test_db, id=21, title="the blocker", type="issue",
            status="implementing",
        )
        insert_item(
            test_db, id=22, title="the dependent", type="issue",
            status="refining-idea",
        )
        _insert_dependency(
            test_db, dependent_item="YOK-22", blocking_item="YOK-21",
            gate_point="activation", rationale="shared schema surface",
        )
        rows = {row["item_id"]: row for row in list_frontier()["ready_rows"]}
        assert "unblocks 1 item" in rows["YOK-21"]["why_ready"]
        assert rows["YOK-21"]["unblocks_count"] == 1


class TestBlockedRows:
    def test_blocked_rows_name_all_three_gate_points(self, test_db):
        insert_item(
            test_db, id=31, title="the blocker", type="issue",
            status="implementing",
        )
        insert_item(
            test_db, id=32, title="gated start", type="issue",
            status="refining-idea",
        )
        insert_item(
            test_db, id=33, title="gated landing", type="issue",
            status="refining-idea",
        )
        insert_item(
            test_db, id=34, title="gated closeout", type="issue",
            status="refining-idea",
        )
        _insert_dependency(
            test_db, dependent_item="YOK-32", blocking_item="YOK-31",
            gate_point="activation", rationale="must start after",
        )
        _insert_dependency(
            test_db, dependent_item="YOK-33", blocking_item="YOK-31",
            gate_point="integration", rationale="must land after",
        )
        _insert_dependency(
            test_db, dependent_item="YOK-34", blocking_item="YOK-31",
            gate_point="closure", rationale="must close after",
        )

        result = list_frontier()
        by_gate = {
            row["gate_point"]: row for row in result["blocked_rows"]
        }
        assert set(by_gate) == {"activation", "integration", "closure"}

        assert by_gate["activation"]["item_id"] == "YOK-32"
        assert by_gate["integration"]["item_id"] == "YOK-33"
        assert by_gate["closure"]["item_id"] == "YOK-34"
        for gate_point, rationale in (
            ("activation", "must start after"),
            ("integration", "must land after"),
            ("closure", "must close after"),
        ):
            row = by_gate[gate_point]
            assert row["blocking_item"] == "YOK-31"
            assert row["satisfaction"] == "status:done"
            assert rationale in row["why"]
            assert row["project"] == "yoke"

        # The frontier computation enforces activation only, so the
        # integration- and closure-gated items stay runnable — the
        # blocked rows are the only visible trace of those edges.
        ready_ids = {row["item_id"] for row in result["ready_rows"]}
        assert "YOK-33" in ready_ids
        assert "YOK-34" in ready_ids
        assert "YOK-32" not in ready_ids

    def test_non_edge_wait_renders_with_empty_gate(self, test_db):
        insert_item(
            test_db, id=41, title="operator hold", type="issue",
            status="refining-idea", blocked=1,
            blocked_reason="waiting on vendor",
        )
        rows = list_frontier()["blocked_rows"]
        assert len(rows) == 1
        row = rows[0]
        assert row["item_id"] == "YOK-41"
        assert row["blocking_item"] == ""
        assert row["gate_point"] == ""
        assert "waiting on vendor" in row["why"]


class TestProjectScope:
    def test_project_omitted_reads_every_registered_project(self, test_db):
        insert_item(
            test_db, id=51, title="yoke work", type="issue",
            status="implementing", project="yoke",
        )
        insert_item(
            test_db, id=52, title="other work", type="issue",
            status="implementing", project="other",
        )
        all_rows = list_frontier()["ready_rows"]
        assert {row["project"] for row in all_rows} == {"yoke", "other"}

        scoped = list_frontier(project="other")["ready_rows"]
        assert [row["item_id"] for row in scoped] == ["YOK-52"]
        assert scoped[0]["project"] == "other"


class TestEventFreeRead:
    def test_read_writes_no_event_rows(self, test_db):
        insert_item(
            test_db, id=61, title="quiet read", type="issue",
            status="implementing",
        )
        insert_item(
            test_db, id=62, title="gated", type="issue",
            status="refining-idea",
        )
        _insert_dependency(
            test_db, dependent_item="YOK-62", blocking_item="YOK-61",
            gate_point="activation", rationale="ordering",
        )
        before = _event_count(test_db)
        list_frontier()
        assert _event_count(test_db) == before

    def test_default_schedule_still_emits(self, test_db):
        # The suppression is opt-in: the same computation with default
        # arguments keeps its telemetry writes.
        from yoke_core.domain.scheduler import compute_schedule

        insert_item(
            test_db, id=71, title="telemetry keeper", type="issue",
            status="implementing",
        )
        before = _event_count(test_db)
        compute_schedule(test_db, project_scope=["yoke"])
        assert _event_count(test_db) > before


class TestHandler:
    def test_handler_returns_both_row_families(self, test_db):
        insert_item(
            test_db, id=81, title="handled", type="issue",
            status="implementing",
        )
        outcome = handle_frontier_list(_request())
        assert outcome.primary_success
        payload = outcome.result_payload
        assert payload["fields"]["ready"] == list(FRONTIER_READY_FIELDS)
        assert [row["item_id"] for row in payload["ready_rows"]] == ["YOK-81"]
        assert payload["blocked_rows"] == []

    def test_handler_unknown_project_is_typed_not_found(self, test_db):
        outcome = handle_frontier_list(_request({"project": "nope"}))
        assert not outcome.primary_success
        assert outcome.error.code == "not_found"
        assert "nope" in outcome.error.message

    def test_handler_bad_payload_types_are_typed_errors(self, test_db):
        for payload in ({"project": 7}, {"wip_cap": "five"}, {"wip_cap": True}):
            outcome = handle_frontier_list(_request(payload))
            assert not outcome.primary_success
            assert outcome.error.code == "payload_invalid"

    def test_handler_requires_global_target(self):
        outcome = handle_frontier_list(
            FunctionCallRequest(
                function="frontier.list",
                actor=ActorContext(actor_id=None, session_id=""),
                target=TargetRef(kind="item", item_id=1),
                payload={},
            ),
        )
        assert not outcome.primary_success
        assert outcome.error.code == "target_invalid"


class TestRegistrationAndAllowlist:
    def test_frontier_list_is_a_registered_claimless_read(self):
        from yoke_core.domain.handlers.__init_register__ import (
            register_all_handlers,
        )
        from yoke_core.domain import yoke_function_registry as registry
        from yoke_core.domain.yoke_function_actor_identity import is_read_only

        registry.reset_registry_for_tests()
        try:
            register_all_handlers()
            entry = registry.lookup("frontier.list")
            assert entry is not None
            assert entry.target_kinds == ("global",)
            assert is_read_only(entry)
        finally:
            registry.reset_registry_for_tests()

    def test_browser_allowlist_contains_frontier_list(self):
        from yoke_core.ui.server import UI_READ_FUNCTION_ALLOWLIST

        assert "frontier.list" in UI_READ_FUNCTION_ALLOWLIST
