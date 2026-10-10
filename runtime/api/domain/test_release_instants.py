"""Release candidates, freeze cutoffs and pipe views preserve native clocks."""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from yoke_contracts.timestamps import InvalidInstant, format_instant, parse_instant
from yoke_core.domain.delivery_release_candidates import (
    completion_order,
    succeeded_flow_runs,
)
from yoke_core.domain.deployment_run_pipe_format import pipe_row
from yoke_core.domain.deployment_run_project_sources import carrying_runs_for_project
from yoke_core.domain.release_delivery_membership import ReleaseDeliveryIndex
from yoke_core.domain.release_delivery_summary import succeeded_runs_for_environment


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kolkata"])
def test_combined_release_candidates_keep_native_order_and_null_last(test_db, zone):
    import json
    from runtime.api.fixtures.backlog_inserts import insert_deployment_run

    test_db.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
    before = parse_instant("1969-12-31T23:59:59.999999Z")
    for run_id, instant in [
        ("own-old", before - timedelta(microseconds=1)),
        ("own-new", before),
        ("own-null", None),
    ]:
        insert_deployment_run(
            test_db,
            id=run_id,
            flow="release-instant",
            status="succeeded",
            created_at=before,
            completed_at=instant,
            target_tier="persistent",
            target_environment_id=7,
            release_lineage="a" * 40,
        )
    insert_deployment_run(
        test_db,
        id="carrier-clock",
        project="carrier",
        flow="carrier-instant",
        status="succeeded",
        created_at=before,
        completed_at=before + timedelta(microseconds=1),
        target_tier="persistent",
        target_environment_id=7,
        release_lineage="b" * 40,
        bound_sources=json.dumps(
            {"projects": [{"project_id": 1, "commit_sha": "a" * 40}]}
        ),
    )
    carriers = carrying_runs_for_project(test_db, 1)
    assert [r["id"] for r in carriers] == ["carrier-clock"]
    assert isinstance(carriers[0]["completed_at"], datetime)
    for result in [
        succeeded_flow_runs(test_db, project_id=1, flows=["release-instant"]),
        succeeded_runs_for_environment(test_db, project_id=1, environment_id=7),
    ]:
        assert [r["id"] for r in result] == [
            "carrier-clock",
            "own-new",
            "own-old",
            "own-null",
        ]
        assert result[-1]["completed_at"] is None
        assert all(r["composition_frozen_at"] is None for r in result)
        assert all(isinstance(r["completed_at"], datetime) for r in result[:-1])


@pytest.mark.parametrize("delta", [-1, 0, 1])
def test_merge_freeze_cutoff_is_exact_before_ancestry(test_db, delta):
    from runtime.api.fixtures.backlog_inserts import insert_item

    freeze = parse_instant("1969-12-31T23:59:59.999999Z")
    insert_item(test_db, id=130, merged_at=freeze + timedelta(microseconds=delta))
    seen = []

    class Walk:
        def __init__(self, *args, **kwargs):
            pass

        def contains(self, sha):
            seen.append(sha)
            return SimpleNamespace(contained=True)

    index = ReleaseDeliveryIndex(
        test_db,
        project_id=1,
        containment_cls=Walk,
        runs=[
            {
                "id": "release-clock",
                "flow": "release-instant",
                "release_lineage": "a" * 40,
                "completed_at": freeze + timedelta(minutes=1),
                "composition_frozen_at": "1969-12-31T18:59:59.999999-05:00",
            }
        ],
    )
    result = index.carrier_for("b" * 40, item_id=130)
    assert bool(result) == (delta <= 0)
    assert seen == (["b" * 40] if delta <= 0 else [])


def test_pipe_boundary_formats_native_clocks_and_preserves_opaque_strings():
    instant = parse_instant("1969-12-31T18:59:59.999999-05:00")
    assert (
        pipe_row([None, instant, "1969-12-31", "evidence"])
        == "|" + format_instant(instant) + "|1969-12-31|evidence"
    )
    assert completion_order({"completed_at": None}) == (False, None)


@pytest.mark.parametrize(
    "bad", ["", "1969-12-31", "1969-12-31T23:59:59", datetime(1969, 12, 31)]
)
def test_invalid_release_clock_cannot_sort_as_missing(bad):
    with pytest.raises(InvalidInstant, match="invalid_instant"):
        completion_order({"completed_at": bad})


def test_native_run_projection_preserves_nullable_clocks():
    from runtime.api.domain.test_deployment_run_list_read import _RunRows
    from yoke_core.domain.deployment_run_list_read import present_deployment_runs

    instant = parse_instant("1969-12-31T23:59:59.999999Z")
    [view] = present_deployment_runs(
        _RunRows(),
        [
            {
                "id": "run-clock-view",
                "status": "succeeded",
                "stages": "[]",
                "created_at": instant,
                "completed_at": None,
                "composition_frozen_at": None,
                "started_at": None,
            }
        ],
        actor_id=None,
        visible_project_ids=None,
        include_carried_work=False,
    )
    assert view["created_at"] == format_instant(instant)
    assert all(
        view[key] is None
        for key in ["completed_at", "composition_frozen_at", "started_at"]
    )
