"""One shared plan preserves case order across machine partitions."""

from runtime.api.domain.test_qa_shared_partition_concurrency import (
    MAC, STUDIO, SESSIONS, MEMBERS, _seed, _case, _begin, _keys,
)
from runtime.api.domain.test_deployment_qa_stage_execution import _complete_case
from yoke_core.domain.qa_plan_execution_state import lock_plan_execution


def test_later_machine_waits_for_earlier_cases(test_db, tmp_path, monkeypatch):
    _seed(
        test_db, tmp_path, monkeypatch,
        [_case("first", MAC), _case("later", STUDIO)],
        separate_plans=False,
    )
    first = _begin(test_db, SESSIONS[0])
    assert _keys(first) == ["first"]
    waiting = _begin(test_db, SESSIONS[1], MEMBERS[1])
    assert waiting["state"] == "waiting"
    assert waiting["shared_execution_wait"]["execution_id"] == first["id"]
    _complete_case(test_db, lock_plan_execution(test_db, first["id"]))
    later = _begin(test_db, SESSIONS[1], MEMBERS[1])
    assert _keys(later) == ["later"]


def test_interleaved_machines_advance_without_skipping_or_deadlock(
    test_db, tmp_path, monkeypatch,
):
    _seed(
        test_db, tmp_path, monkeypatch,
        [_case("first", MAC), _case("second", STUDIO), _case("third", MAC)],
        separate_plans=False,
    )
    for key in ("first", "second", "third"):
        execution = _begin(test_db, SESSIONS[0])
        assert _keys(execution) == [key]
        _complete_case(test_db, lock_plan_execution(test_db, execution["id"]))
