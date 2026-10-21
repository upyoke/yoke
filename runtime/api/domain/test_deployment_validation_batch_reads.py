"""Validation round trips stay bounded as the member and rework sets grow."""

from unittest.mock import patch

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.domain.test_deployment_run_composition_lock_window import (
    _carrying_run,
    _validate,
)
from runtime.api.domain.test_deployment_run_start_lock_window import _known_carried
from runtime.api.tools.read_query_profile import CountedConnection
from yoke_core.domain.deployment_runs_batch_compatibility import _not_delivery_ready
from yoke_core.domain.deployment_run_skipped_candidates import carried_items_in_rework
from yoke_core.domain.deployment_start_timing import timing_scope
from yoke_core.domain.schema_read_scope import composition_reads
from yoke_core.domain import workflow_item_binding_validation as bindings


def test_validation_statement_count_does_not_grow_with_members(test_db):
    counts = []
    for name, base, count in (("small", 21000, 2), ("large", 22000, 30)):
        members = list(range(base, base + count))
        run_id = _carrying_run(test_db, name, members)
        (ok, message), recorder = _validate(test_db, run_id)
        assert ok, message
        counts.append(len(recorder.log))
    assert counts[0] == counts[1], counts


def test_rework_reads_and_labels_do_not_grow_with_candidates(test_db):
    counts = []
    for base, count in ((23000, 2), (24000, 30)):
        ids = list(range(base, base + count))
        for item_id in ids:
            insert_item(
                test_db,
                id=item_id,
                project_sequence=item_id,
                workflow_id="dash",
                status="implementing",
            )
        test_db.commit()
        counted = CountedConnection(test_db)
        with composition_reads():
            found = carried_items_in_rework(counted, "absent", _known_carried(ids))
            labels = _not_delivery_ready(counted, found)
        assert found == tuple((item_id, "implementing") for item_id in ids)
        assert len(labels) == count
        assert all("status=implementing" in label for label in labels)
        counts.append(sum(counted.counts.values()))
    assert counts[0] == counts[1], counts


def test_shared_workflow_version_is_interpreted_once_and_status_is_fresh(test_db):
    ids = [25000, 25001]
    for item_id in ids:
        insert_item(test_db, id=item_id, workflow_id="dash", status="release")
    parser = bindings.workflow_runtime_from_row
    with patch.object(bindings, "workflow_runtime_from_row", wraps=parser) as parse:
        pinned = bindings.read_pinned_items(test_db, ids)
    assert parse.call_count == 1
    assert pinned[ids[0]].runtime is pinned[ids[1]].runtime
    test_db.execute("UPDATE items SET status='implementing' WHERE id=%s", (ids[0],))
    assert bindings.read_pinned_items(test_db, ids)[ids[0]].status == "implementing"


def test_validation_emits_substep_timings(test_db):
    run_id = _carrying_run(test_db, "timed", [26000, 26001])
    with timing_scope(run_id, collect=True) as records:
        (ok, message), _ = _validate(test_db, run_id)
    assert ok, message
    steps = {record["step"] for record in records if record["phase"] == "end"}
    assert {
        "validation_bound_sources",
        "validation_custody",
        "validation_carried_work",
        "validation_enrollment_plan",
        "validation_judgement",
    } <= steps


@pytest.mark.parametrize(
    "status,ready", [("release", True), ("done", False), ("cancelled", False)]
)
def test_pinned_readiness_keeps_terminal_rules(test_db, status, ready):
    insert_item(test_db, id=27000, workflow_id="dash", status=status)
    labels = _not_delivery_ready(test_db, [(27000, status)])
    assert (not labels) is ready
    if status == "done":
        assert not _not_delivery_ready(test_db, [(27000, status)], allow_completed=True)


def test_held_candidate_notice_reads_do_not_grow_with_items(test_db):
    from runtime.api.domain.test_deployment_membership_round_trips import _created_run
    from yoke_core.domain.deployment_run_skipped_candidates import _held_descriptions
    from yoke_core.domain.deployment_run_unheld_candidates import HeldCandidate

    counts = []
    for name, base, count in (("held-small", 28000, 2), ("held-large", 29000, 30)):
        ids = list(range(base, base + count))
        run_id = _created_run(test_db, name, ids)
        counted = CountedConnection(test_db)
        held = tuple(HeldCandidate(i, f"REF-{i}", run_id, "executing") for i in ids)
        lines = _held_descriptions(counted, run_id, held)
        assert len(lines) == count
        assert all(f"held by {run_id} (executing)" in line for line in lines)
        counts.append(sum(counted.counts.values()))
    assert counts[0] == counts[1] == 2
