"""Dispatch skips empty members until a materialization input changes."""

from runtime.api.domain.test_deployment_qa_stage_execution import _plan, _seed_run, _stages
from runtime.api.domain.test_no_obligation_member_close_out import _no_obligation
from runtime.api.fixtures.statement_counter import CountingConnection
from yoke_core.domain import deployment_qa_dispatch_preparation as preparation
from yoke_core.domain.deployment_qa_empty_members import empty_members


def test_fifty_members_only_reread_the_ten_owing_cases(test_db, monkeypatch):
    run_id = "run-empty-members"
    members = list(range(9401, 9451))
    stages = _stages(_plan(test_db, "empty-cohort"))
    _seed_run(test_db, run_id=run_id, stages=stages, members=members)
    empty = members[:40]
    for member in empty:
        _no_obligation(test_db, member, reason="no runtime behavior changed")
    test_db.commit()
    reads = []
    real = preparation._read_member

    def read(*args):
        reads.append(args[-1])
        return real(*args)

    monkeypatch.setattr(preparation, "_read_member", read)
    assert preparation.prepare_members(test_db, stages[1], run_id=run_id, members=members) == {}
    assert empty_members(test_db, run_id, "item-qa") == set(empty)
    reads.clear()
    counting = CountingConnection(test_db)
    assert preparation.prepare_members(counting, stages[1], run_id=run_id, members=members) == {}
    assert reads == []
    assert not any("FOR UPDATE" in sql for sql in counting.statements)
    # A direct case lineage change invalidates the remembered emptiness.
    test_db.execute("UPDATE qa_requirements SET instructions='new runtime behavior' WHERE item_id=%s", (empty[0],))
    assert empty_members(test_db, run_id, "item-qa") == set()
