"""Overview targets resolve once per subject and refresh on the next read."""

from collections import Counter

from runtime.api.domain.test_deployment_qa_dispatch_reads import _seed
from runtime.api.fixtures.statement_counter import CountingConnection
from yoke_core.domain import deployment_qa_execution_target as execution
from yoke_core.domain import deployment_qa_target_continuity as continuity
from yoke_core.domain.deployment_qa_presentation_reads import (
    presentation_operation,
    uncached_presentation,
)
from yoke_core.domain.deployment_qa_run_acceptance import member_qa_standings


def test_overview_target_queries_and_resolutions_are_bounded(test_db, monkeypatch):
    calls = Counter()
    for module, name in (
        (execution, "_resolve_execution_target"),
        (continuity, "_resolve_settlement_target"),
    ):
        original = getattr(module, name)

        def count(conn, subject, *args, _original=original, _name=name):
            calls[(_name, subject["id"], subject.get("member_item_id"))] += 1
            return _original(conn, subject, *args)

        monkeypatch.setattr(module, name, count)

    counts = []
    for run_id, members in (
        ("targets-small", tuple(range(9701, 9703))),
        ("targets-large", tuple(range(9801, 9811))),
    ):
        _seed(test_db, run_id, members)
        calls.clear()
        conn = CountingConnection(test_db)
        subjects = [(run_id, member, "item-qa") for member in members]

        @presentation_operation
        def overview():
            first = member_qa_standings(conn, subjects)
            assert member_qa_standings(conn, subjects) == first
            return first

        assert len(overview()) == len(members)
        assert all(n == 1 for n in calls.values()), calls
        target_queries = {
            sql: n
            for sql, n in conn.statements.items()
            if "FROM qa_requirements WHERE deployment_run_id IN" in sql
            or "FROM deployment_stage_receipts WHERE run_id IN" in sql
            or "FROM environments e JOIN sites" in sql
        }
        assert len(target_queries) == 2, target_queries
        assert set(target_queries.values()) == {1}, target_queries
        counts.append(sum(target_queries.values()))
        calls.clear()
        overview()
        assert all(n == 1 for n in calls.values()), calls
        calls.clear()
    assert counts[0] == counts[1]


def test_new_presentation_and_uncached_writes_see_new_receipt(test_db, monkeypatch):
    from runtime.api.domain import test_deployment_run_target_takeover as takeover
    from runtime.api.domain.test_deployment_qa_successor_receipt import _arrive
    from runtime.api.domain.test_deployment_qa_takeover_identity import _execution
    from yoke_core.domain.deployment_qa_stage_contract import (
        deployment_qa_stage_subject,
    )

    _execution(test_db, monkeypatch)
    _arrive(test_db, ready=False)
    subject = deployment_qa_stage_subject(
        test_db,
        run_id=takeover.NEW,
        stage_name=takeover.RUN_QA_STAGE,
        member_item_id=None,
    )

    @presentation_operation
    def overview():
        old = execution.deployment_qa_execution_target(test_db, subject)
        assert old["deployment"]["run_id"] == takeover.OLD
        _arrive(test_db, ready=True)
        assert execution.deployment_qa_execution_target(test_db, subject) == old
        with uncached_presentation():
            fresh = execution.deployment_qa_execution_target(test_db, subject)
            assert fresh["deployment"]["run_id"] == takeover.NEW
        return old

    old = overview()

    @presentation_operation
    def next_overview():
        fresh = execution.deployment_qa_execution_target(test_db, subject)
        assert fresh["deployment"]["run_id"] == takeover.NEW
        settled = continuity.settlement_target(test_db, subject, fresh)
        assert settled == old
        assert continuity.settlement_target(test_db, subject, fresh) == old

    next_overview()
