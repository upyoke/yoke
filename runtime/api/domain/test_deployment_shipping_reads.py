"""Shipping shares authority reads at the observed release/member scale."""

import json
import sys
from unittest.mock import patch
from collections import Counter
from time import perf_counter

from yoke_contracts.api.function_call import FunctionCallResponse

from runtime.api.domain.test_deployment_qa_stage_execution import (
    _complete_case,
    _plan,
    _seed_run,
    _stages,
)
from runtime.api.domain.test_deployment_qa_shared_plans import _attach, _fail
from yoke_core.domain.deployment_qa_run_acceptance import (
    current_item_qa,
    member_qa_standings,
)
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution


class CountedConnection:
    def __init__(self, conn):
        self.conn = conn
        self.queries = Counter()
        self.callers = Counter()

    def execute(self, sql, params=()):
        self.queries[sql] += 1
        caller = sys._getframe(1)
        while caller.f_globals["__name__"] == "yoke_core.domain.db_helpers":
            caller = caller.f_back
        self.callers[f"{caller.f_globals['__name__']}.{caller.f_code.co_name}"] += 1
        return self.conn.execute(sql, params)

    def close(self):
        pass

    def __getattr__(self, name):
        return getattr(self.conn, name)


def test_member_presentation_shares_reads_without_reusing_next_request(test_db):
    plan = _plan(test_db, "shipping-shared-check")
    stages = _stages(plan)
    stages[1].pop("cases")
    subjects = []
    requirement_ids = []
    for index in range(12):
        run_id = f"shipping-run-{index}"
        count = 17 if index < 2 else 16
        members = tuple(20000 + index * 20 + n for n in range(count))
        _seed_run(test_db, run_id=run_id, stages=stages, members=members)
        for member in members:
            _attach(test_db, member, plan)
            subjects.append((run_id, member, "item-qa"))
        materialize_deployment_qa_stage(
            test_db,
            deployment_run_id=run_id,
            deployment_stage="item-qa",
            deployment_member_item_id=members[0],
        )
        execution = begin_plan_execution(
            test_db,
            deployment_run_id=run_id,
            deployment_stage="item-qa",
            deployment_member_item_id=members[0],
            actor_id="2",
            session_id="shipping-read",
        )
        requirement_ids.append(_complete_case(test_db, execution))
        assert deployment_qa_stage_status(
            test_db,
            run_id=run_id,
            stage_name="item-qa",
            member_item_id=members[0],
        )["accepted"]
    assert len(subjects) == 194
    _fail(test_db, requirement_ids[-1])
    conn = CountedConnection(test_db)
    start = perf_counter()
    answers = member_qa_standings(conn, subjects)
    elapsed = perf_counter() - start
    assert len(answers) == 194
    assert sum(answer["state"] == "accepted" for answer in answers.values()) == 178
    assert all(
        answers[(run, member)]["state"] == "cases unresolved"
        for run, member, _ in subjects[-16:]
    )
    baseline = CountedConnection(test_db)
    before = perf_counter()
    for run, member, stage in subjects:
        expected = current_item_qa(
            baseline, run_id=run, item_id=member, current_stage=stage
        )
        assert answers[(run, member)] == {
            "state": expected.state,
            "stage": expected.stage,
            "reason": expected.reason,
            "failed_requirement_ids": list(expected.failed_requirement_ids),
        }
    before_elapsed = perf_counter() - before
    assert sum(conn.queries.values()) < sum(baseline.queries.values())
    run_reads = sum(n for sql, n in conn.queries.items() if "o.id AS tenant_id" in sql)
    member_reads = sum(
        n
        for sql, n in conn.queries.items()
        if "SELECT dri.item_id,dri.requirement_snapshot" in sql
    )
    receipt_reads = sum(
        n
        for sql, n in conn.queries.items()
        if "SELECT id FROM deployment_stage_receipts" in sql
    )
    assert (run_reads, member_reads, receipt_reads) == (1, 0, 0)
    assert conn.callers["yoke_core.domain.deployment_qa_presentation_facts.read"] <= 7
    assert (
        conn.callers["yoke_core.domain.deployment_requirement_snapshots._plan_snapshot"]
        == 0
    )
    assert (
        conn.callers[
            "yoke_core.domain.deployment_stage_receipts.deployment_stage_receipt_for_qa"
        ]
        == 0
    )
    assert conn.callers["yoke_core.domain.item_ref_render.fetch_item_ref_rows"] == 0
    print(
        f"Shipping: runs=12 members=194 queries={sum(conn.queries.values())} "
        f"run_reads={run_reads} member_reads={member_reads} receipt_reads={receipt_reads} "
        f"elapsed_seconds={elapsed:.3f} "
        f"unbatched_queries={sum(baseline.queries.values())} "
        f"unbatched_seconds={before_elapsed:.3f}"
    )
    # Include recorded carried work and real historical landing containment in
    # the complete-list profile; member QA alone does not describe its cost.
    run_ids = sorted({run for run, _, _ in subjects})
    bound = {
        "schema": 1,
        "projects": [{"project_id": 3, "project": "platform", "commit_sha": "b" * 40}],
        "inputs": {"consumer_sha": "b" * 40},
        "preparation_receipt": {
            "request_id": "shipping-preparation",
            "payload": "x" * 800000,
        },
    }
    for run_id in run_ids:
        members = [member for run, member, _ in subjects if run == run_id]
        snapshot = {
            "answers": [
                {
                    "project_id": 1,
                    "id": member,
                    "merge_sha": "a" * 40,
                    "state": "contained",
                }
                for member in members
            ]
        }
        carried = {
            "schema": 1,
            "items": [
                {"item_id": member, "ref": f"MEM-{member}", "project_id": 1}
                for member in members
            ],
            "commits": [],
        }
        test_db.execute(
            "UPDATE deployment_runs SET carried_work=%s,candidate_containment=%s,"
            "bound_sources=%s WHERE id=%s",
            (json.dumps(carried), json.dumps(snapshot), json.dumps(bound), run_id),
        )
    for index in range(148):
        test_db.execute(
            "INSERT INTO deployment_runs(id,project_id,flow,status,created_at,completed_at,"
            "target_tier,target_environment_id,candidate_containment,carried_work) "
            "SELECT %s,project_id,flow,'succeeded',created_at,created_at,"
            "target_tier,target_environment_id,candidate_containment,carried_work FROM deployment_runs WHERE id=%s",
            (f"shipping-history-{index}", run_ids[index % 12]),
        )
    from yoke_core.domain.handlers.deployment_runs import handle_deployment_run_list
    from runtime.api.domain.handlers.deployment_handler_test_support import (
        deployment_request,
    )

    full = CountedConnection(test_db)
    with patch("yoke_core.domain.deployment_run_list_read.connect", return_value=full):
        outcome = handle_deployment_run_list(
            deployment_request(
                function="deployment_runs.list",
                payload={"relevance": "overview"},
            )
        )
    assert outcome.primary_success
    complete = outcome.result_payload["rows"]
    assert {row["id"] for row in complete} == set(run_ids)
    assert sum(len(row["member_items"]) for row in complete) == 194
    assert sum(full.queries.values()) < 60
    assert all(row["carried_work"]["items"] for row in complete)
    serialized = FunctionCallResponse(
        function="deployment_runs.list",
        version="v1",
        success=True,
        result=outcome.result_payload,
    ).model_dump_json()
    assert len(serialized.encode()) < 1_000_000
    for row in complete:
        assert row["bound_sources"] == {
            key: value for key, value in bound.items() if key != "preparation_receipt"
        }
    # Only Shipping's projection omits the bulky frozen receipt. Driver recovery
    # and detail reads still recover the exact original committed record.
    from yoke_core.domain.deployment_runs_crud_query import get_run

    with patch(
        "yoke_core.domain.deployment_runs_crud_query.connect", return_value=full
    ):
        stored = get_run(run_ids[0])
    assert json.loads(stored["bound_sources"]) == bound
    print(
        f"Shipping serialized overview bytes={len(serialized.encode())} omitted_receipt_bytes={800000 * len(run_ids)}"
    )
    print(
        f"Shipping complete handler: local_authority=true approval_records=0 runs=12 members=194 history_runs=148 "
        f"queries={sum(full.queries.values())} dominant_callers={full.callers.most_common(30)}"
    )
    print(f"Shipping member QA dominant_callers={conn.callers.most_common(12)}")
    # A later request must read a changed verdict, rather than reuse a cached pass.
    _fail(test_db, requirement_ids[0])
    changed = member_qa_standings(conn, subjects[:17])
    assert all(answer["state"] == "cases unresolved" for answer in changed.values())


def test_combined_overview_preserves_each_project_window_and_shared_members(test_db):
    from datetime import timedelta
    from runtime.api.fixtures.backlog_inserts import insert_item
    from yoke_core.domain.db_helpers import utc_now
    from yoke_core.domain.deployment_run_list_read import list_deployment_runs

    own = insert_item(test_db, id=30001, project="quiet-project")
    quiet_project = int(own["project_id"])
    _seed_run(
        test_db, run_id="quiet-active", stages=_stages(_plan(test_db)), members=(30002,)
    )
    # This run is shared across the two projects, independent of its owner.
    test_db.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,added_at,requirement_snapshot) "
        "VALUES ('quiet-active',%s,%s,'{}')",
        (int(own["id"]), utc_now()),
    )
    test_db.execute(
        "UPDATE deployment_runs SET current_stage='deploy',created_at=%s,"
        "carried_work=%s WHERE id='quiet-active'",
        (utc_now() - timedelta(hours=2), '{"schema":1,"items":[],"commits":[]}'),
    )
    for index in range(25):
        test_db.execute(
            "INSERT INTO deployment_runs(id,project_id,flow,status,current_stage,created_at,carried_work) "
            "SELECT %s,1,flow,'executing','deploy',%s,carried_work "
            "FROM deployment_runs WHERE id='quiet-active'",
            (f"busy-active-{index:02}", utc_now() - timedelta(minutes=index)),
        )
    conn = CountedConnection(test_db)
    with patch("yoke_core.domain.deployment_run_list_read.connect", return_value=conn):
        all_rows = list_deployment_runs(
            project=None, status=None, limit=20, relevance="overview"
        )
        own_rows = list_deployment_runs(
            project=str(quiet_project), status=None, limit=20, relevance="overview"
        )
    assert len(all_rows) == 21
    assert len({row["id"] for row in all_rows}) == 21
    shared = next(row for row in all_rows if row["id"] == "quiet-active")
    assert {member["id"] for member in shared["member_items"]} == {30001, 30002}
    assert {row["id"] for row in own_rows} == {"quiet-active"}
    with (
        patch("yoke_core.domain.deployment_run_list_read.connect", return_value=conn),
        patch(
            "yoke_core.domain.deployment_run_list_read.actor_visible_project_ids",
            return_value={quiet_project},
        ),
    ):
        visible = list_deployment_runs(
            project=None, status=None, limit=20, relevance="overview"
        )
    assert {row["id"] for row in visible} == {"quiet-active"}
