"""Delivery from recorded membership and recency, before git.

The Frontier box used to ask ancestry for every merge no run listed in
carried work. Membership in a succeeded run is already delivery; a merge
newer than the newest succeeded candidate is already not. These cases prove
those answers, and that a dishonest carried-work payload cannot substitute.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.backlog_inserts import insert_deployment_run, insert_item
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import release_delivery_summary as summary_module
from yoke_core.domain.deployment_run_candidate_containment import (
    CONTAINED,
    NOT_CONTAINED,
    ContainmentVerdict,
)
from yoke_core.domain.item_merge_receipt_document import record_entry
from yoke_core.domain.release_delivery_summary import (
    ReleaseCandidates,
    delivery_summary,
    recorded_merge_shas_for_items,
)

FLOW = "yoke-hosted-production"
ITEM_ID = 4301
PROJECT_ID = 1
ENVIRONMENT_ID = 7
MERGE = "a" * 40
LINEAGE = "d" * 40
COMPLETED = "2026-09-18T00:00:00Z"


class _ForbiddenWalk:
    """Ancestry must not run on a path that records already answer."""

    def __init__(self, *args, **kwargs):
        raise AssertionError("ancestry walk must not run")


def _landing(conn, merge_sha: str = MERGE) -> None:
    record_entry(
        conn,
        item_id=ITEM_ID,
        branch=f"LANE-{ITEM_ID}",
        target="main",
        commit_sha=merge_sha,
        merge_sha=merge_sha,
    )


def _run(conn, run_id: str, *, carried: list[str], contents_known: bool | None = True):
    payload: dict = {"items": [{"ref": "YOK-1", "commit_shas": carried}]}
    if contents_known is not None:
        payload["derivation"] = {"contents_known": contents_known}
    insert_deployment_run(
        conn,
        id=run_id,
        project_id=PROJECT_ID,
        status="succeeded",
        flow=FLOW,
        target_tier="persistent",
        release_lineage=LINEAGE,
        target_environment_id=ENVIRONMENT_ID,
        carried_work=json.dumps(payload),
        completed_at=COMPLETED,
    )


def _member(conn, run_id: str, item_id: int = ITEM_ID) -> None:
    conn.execute(
        "INSERT INTO deployment_run_items (run_id, item_id, added_at) "
        "VALUES (%s, %s, %s)",
        (run_id, item_id, COMPLETED),
    )


def _summary(conn, *, flow=FLOW):
    merges = recorded_merge_shas_for_items(conn, [ITEM_ID]).get(ITEM_ID, ())
    return delivery_summary(
        merges=merges,
        candidates=ReleaseCandidates(
            conn,
            project_id=PROJECT_ID,
            environment_id=ENVIRONMENT_ID,
            flow=flow,
        ),
        item_id=ITEM_ID,
    )


def test_a_member_of_a_succeeded_run_is_delivered_without_git(monkeypatch) -> None:
    monkeypatch.setattr(summary_module, "CandidateContainment", _ForbiddenWalk)
    with test_database() as conn:
        _landing(conn)
        _run(conn, "run-1", carried=[])
        _member(conn, "run-1")
        conn.commit()
        result = _summary(conn)

    assert (result.merges, result.deployed, result.not_deployed) == (1, 1, 0)
    assert result.flow == FLOW


def test_a_merge_newer_than_the_candidate_is_not_delivered_without_git(
    monkeypatch,
) -> None:
    monkeypatch.setattr(summary_module, "CandidateContainment", _ForbiddenWalk)
    with test_database() as conn:
        insert_item(
            conn,
            id=ITEM_ID,
            title="landed after the candidate",
            status="release",
            merged_at="2026-09-20T12:00:00Z",
            project_id=PROJECT_ID,
        )
        _landing(conn)
        _run(conn, "run-1", carried=[])
        conn.commit()
        result = _summary(conn)

    assert (result.merges, result.deployed, result.not_deployed) == (1, 0, 1)


def test_a_merge_before_the_candidate_that_is_not_a_member_still_uses_ancestry(
    monkeypatch,
) -> None:
    seen: list[str] = []

    class _Walk:
        def __init__(self, conn, project_id, *, candidate_lineage):
            pass

        def contains(self, commit_sha):
            seen.append(commit_sha)
            return ContainmentVerdict(state=CONTAINED)

    monkeypatch.setattr(summary_module, "CandidateContainment", _Walk)
    with test_database() as conn:
        insert_item(
            conn,
            id=ITEM_ID,
            title="merged before, never enrolled",
            status="release",
            merged_at="2026-09-17T00:00:00Z",
            project_id=PROJECT_ID,
        )
        _landing(conn)
        _run(conn, "run-1", carried=["e" * 40])
        conn.commit()
        result = _summary(conn)

    assert (result.merges, result.deployed, result.not_deployed) == (1, 1, 0)
    assert seen == [MERGE]


@pytest.mark.parametrize("route", ["own-environment", "own-persistent", "bound"])
@pytest.mark.parametrize(
    "merged_at,frozen_at,recorded,expected_deployed,walks",
    [
        ("2026-09-17T12:00:00Z", "2026-09-17T06:00:00Z", "", 0, 0),
        ("2026-09-17T12:00:00Z", "2026-09-17T06:00:00Z", "carried", 1, 0),
        ("2026-09-17T12:00:00Z", "2026-09-17T06:00:00Z", "member", 1, 0),
        ("2026-09-17T12:00:00Z", "", "", 1, 1),
        ("2026-09-17T06:00:00Z", "2026-09-17T06:00:00Z", "", 1, 1),
        ("2026-09-17T03:00:00Z", "2026-09-17T06:00:00Z", "", 1, 1),
        (None, "2026-09-17T06:00:00Z", "", 1, 1),
    ],
)
def test_delivery_uses_freeze_after_recorded_carriage(
    monkeypatch,
    route,
    merged_at,
    frozen_at,
    recorded,
    expected_deployed,
    walks,
) -> None:
    seen: list[str] = []

    class _Walk:
        def __init__(self, conn, project_id, *, candidate_lineage):
            assert candidate_lineage == LINEAGE

        def contains(self, commit_sha):
            seen.append(commit_sha)
            return ContainmentVerdict(state=CONTAINED)

    monkeypatch.setattr(summary_module, "CandidateContainment", _Walk)
    with test_database() as conn:
        insert_item(
            conn,
            id=ITEM_ID,
            title="release cutoff",
            status="release",
            merged_at=merged_at,
            project_id=PROJECT_ID,
        )
        _landing(conn)
        carried = [MERGE] if recorded == "carried" else []
        slice_payload = {
            "project_id": PROJECT_ID,
            "items": [{"commit_shas": carried}],
        }
        payload = {
            "derivation": {"contents_known": True},
            "items": slice_payload["items"],
            "bound_projects": [slice_payload],
        }
        run_fields = {"project_id": PROJECT_ID}
        if route == "bound":
            run_fields = {
                "project": "carrier",
                "bound_sources": json.dumps(
                    {
                        "projects": [
                            {
                                "project_id": PROJECT_ID,
                                "commit_sha": LINEAGE,
                            }
                        ]
                    }
                ),
            }
        insert_deployment_run(
            conn,
            id="run-cutoff",
            flow=FLOW,
            status="succeeded",
            created_at="2026-09-17T00:00:00Z",
            completed_at=COMPLETED,
            composition_frozen_at=frozen_at,
            release_lineage="e" * 40 if route == "bound" else LINEAGE,
            target_tier="persistent",
            target_environment_id=ENVIRONMENT_ID,
            carried_work=json.dumps(payload),
            **run_fields,
        )
        if recorded == "member":
            _member(conn, "run-cutoff")
        conn.commit()
        result = _summary(conn, flow="" if route == "own-persistent" else FLOW)

    assert result.merges == 1
    assert result.deployed == expected_deployed
    assert result.not_deployed == 1 - expected_deployed
    assert seen == [MERGE] * walks


def test_unknown_carried_work_forces_the_ancestry_fallback(monkeypatch) -> None:
    seen: list[str] = []

    class _Walk:
        def __init__(self, conn, project_id, *, candidate_lineage):
            pass

        def contains(self, commit_sha):
            seen.append(commit_sha)
            return ContainmentVerdict(state=NOT_CONTAINED)

    monkeypatch.setattr(summary_module, "CandidateContainment", _Walk)
    with test_database() as conn:
        insert_item(
            conn,
            id=ITEM_ID,
            title="carried work could not look",
            status="release",
            merged_at="2026-09-17T00:00:00Z",
            project_id=PROJECT_ID,
        )
        _landing(conn)
        _run(conn, "run-1", carried=[MERGE], contents_known=False)
        conn.commit()
        result = _summary(conn)

    assert (result.merges, result.deployed, result.not_deployed) == (1, 0, 1)
    assert seen == [MERGE]


def test_checkout_not_refreshed_is_not_a_fast_delivery(monkeypatch) -> None:
    seen: list[str] = []

    class _Walk:
        def __init__(self, conn, project_id, *, candidate_lineage):
            pass

        def contains(self, commit_sha):
            seen.append(commit_sha)
            return ContainmentVerdict(state=NOT_CONTAINED)

    monkeypatch.setattr(summary_module, "CandidateContainment", _Walk)
    with test_database() as conn:
        insert_item(
            conn,
            id=ITEM_ID,
            title="stale checkout carried work",
            status="release",
            merged_at="2026-09-17T00:00:00Z",
            project_id=PROJECT_ID,
        )
        _landing(conn)
        insert_deployment_run(
            conn,
            id="run-1",
            project_id=PROJECT_ID,
            status="succeeded",
            flow=FLOW,
            target_tier="persistent",
            release_lineage=LINEAGE,
            target_environment_id=ENVIRONMENT_ID,
            carried_work=json.dumps(
                {
                    "derivation": {"contents_known": True},
                    "items": [{"ref": "YOK-1", "commit_shas": [MERGE]}],
                    "warnings": [{"reason": "checkout_not_refreshed"}],
                }
            ),
            completed_at=COMPLETED,
        )
        conn.commit()
        result = _summary(conn)

    assert (result.merges, result.deployed, result.not_deployed) == (1, 0, 1)
    assert seen == [MERGE]
