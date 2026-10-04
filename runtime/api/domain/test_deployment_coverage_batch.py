"""Set-based coverage preserves per-member authority and bounded reads."""

from unittest.mock import patch
import pytest
from runtime.api.domain.test_deployment_member_run_coverage import (
    _flow,
    _run,
    _item,
    RUN_SCOPED_STAGES,
    ITEM_SCOPED_STAGES,
)
from yoke_core.domain.deployment_member_coverage_batch import member_run_coverages
from yoke_core.domain.deployment_member_run_coverage import member_run_coverage
from yoke_core.domain import deployment_item_flow_resolution as resolution
from yoke_core.domain.schema_read_scope import composition_reads


@pytest.mark.parametrize("stages", [RUN_SCOPED_STAGES, ITEM_SCOPED_STAGES])
def test_batch_matches_single_members_and_resolves_completion_once(test_db, stages):
    _flow(test_db, "batch-run", stages)
    _run(test_db, "run-batch", "batch-run")
    ids = tuple(range(9601, 9621))
    for index, item_id in enumerate(ids):
        _item(test_db, item_id, flow="batch-run" if index % 2 else "other-flow")
    test_db.commit()
    expected = {
        value: member_run_coverage(test_db, run_id="run-batch", item_id=value)
        for value in ids
    }
    with patch(
        "yoke_core.domain.deployment_member_coverage_batch.item_completion_flow_facts",
        wraps=resolution.item_completion_flow_facts,
    ) as facts:
        with composition_reads():
            result = member_run_coverages(test_db, run_id="run-batch", item_ids=ids)
            again = member_run_coverages(test_db, run_id="run-batch", item_ids=ids)
        assert result == again == expected
        facts.assert_called_once_with(test_db, ids)
    for index, item_id in enumerate(ids):
        assert result[item_id].closes == bool(index % 2)
        assert result[item_id].checks == (stages == ITEM_SCOPED_STAGES)


def test_missing_item_and_run_remain_named_refusals(test_db):
    _flow(test_db, "missing-batch", RUN_SCOPED_STAGES)
    _run(test_db, "run-missing-batch", "missing-batch")
    with pytest.raises(LookupError, match="item .* not found"):
        member_run_coverages(test_db, run_id="run-missing-batch", item_ids=[99999])
    with pytest.raises(LookupError, match="deployment run .* not found"):
        member_run_coverages(test_db, run_id="absent", item_ids=[99999])


def test_coverage_query_count_does_not_grow_with_member_count(test_db):
    _flow(test_db, "bounded-run", RUN_SCOPED_STAGES)
    _run(test_db, "run-bounded", "bounded-run")
    ids = tuple(range(9651, 9671))
    for item_id in ids:
        _item(test_db, item_id, flow="bounded-run")
    test_db.commit()
    with patch.object(test_db, "execute", wraps=test_db.execute) as reads:
        with composition_reads():
            member_run_coverages(test_db, run_id="run-bounded", item_ids=ids[:1])
        single = reads.call_count
        reads.reset_mock()
        with composition_reads():
            member_run_coverages(test_db, run_id="run-bounded", item_ids=ids)
        assert reads.call_count == single
