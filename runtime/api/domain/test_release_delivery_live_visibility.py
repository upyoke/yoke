"""In-flight candidate containment is a card join, never membership.

A schema-v1 stage run enrolls nobody, so a live box that indexes only by
member rows is blank for the whole execution. These cases prove the card
can still name that run from containment, that the membership table is
untouched, and that an in-flight containment is not counted as deployed.
"""

from __future__ import annotations

from runtime.api.fixtures.backlog_inserts import insert_deployment_run, insert_item
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import release_delivery_live_visibility as visibility
from yoke_core.domain.deployment_run_candidate_containment import (
    CONTAINED,
    NOT_CONTAINED,
    ContainmentVerdict,
)
from yoke_core.domain.item_merge_receipt_document import record_entry
from yoke_core.domain.release_delivery_live_visibility import live_visible_items
from yoke_core.domain.release_delivery_summary import (
    ReleaseCandidates,
    delivery_summary,
    recorded_merge_shas_for_items,
)

FLOW = "yoke-hosted-stage-consumer-bound"
PROD_FLOW = "yoke-hosted-production"
ITEM_ID = 5521
PROJECT_ID = 1
ENVIRONMENT_ID = 7
MERGE = "a" * 40
LINEAGE = "d" * 40
COMPLETED = "2026-09-18T00:00:00Z"


class _ForbiddenWalk:
    def __init__(self, *args, **kwargs):
        raise AssertionError("ancestry walk must not run")


def _contained_walk(answer):
    class _Walk:
        def __init__(self, conn, project_id, *, candidate_lineage):
            self._lineage = candidate_lineage

        def contains(self, commit_sha):
            return answer(commit_sha, self._lineage)

    return _Walk


def _landing(conn, item_id: int = ITEM_ID, merge_sha: str = MERGE) -> None:
    record_entry(
        conn,
        item_id=item_id,
        branch=f"LANE-{item_id}",
        target="main",
        commit_sha=merge_sha,
        merge_sha=merge_sha,
    )


def _open_item(conn) -> None:
    insert_item(
        conn,
        id=ITEM_ID,
        title="waiting on a stage run",
        status="release",
        merged_at="2026-09-20T12:00:00Z",
        project_id=PROJECT_ID,
        deployment_flow=PROD_FLOW,
    )
    _landing(conn)


def _executing_stage(conn, run_id: str = "run-stage") -> None:
    insert_deployment_run(
        conn,
        id=run_id,
        project_id=PROJECT_ID,
        status="executing",
        flow=FLOW,
        target_tier="persistent",
        release_lineage=LINEAGE,
        target_environment_id=ENVIRONMENT_ID,
        current_stage="item-qa",
    )


def _member_count(conn, run_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM deployment_run_items WHERE run_id=%s",
        (run_id,),
    ).fetchone()
    return int(row["n"] if hasattr(row, "keys") else row[0])


def test_an_executing_stage_run_names_the_item_its_candidate_contains(
    monkeypatch,
) -> None:
    seen: list[str] = []

    def answer(commit_sha, lineage):
        seen.append(commit_sha)
        assert lineage == LINEAGE
        return ContainmentVerdict(state=CONTAINED)

    monkeypatch.setattr(visibility, "CandidateContainment", _contained_walk(answer))
    with test_database() as conn:
        _open_item(conn)
        _executing_stage(conn)
        conn.commit()
        items = live_visible_items(
            conn,
            {
                "id": "run-stage",
                "project_id": PROJECT_ID,
                "status": "executing",
                "release_lineage": LINEAGE,
            },
        )
        members = _member_count(conn, "run-stage")

    assert items == [{"id": ITEM_ID}]
    assert seen == [MERGE]
    assert members == 0


def test_a_candidate_that_does_not_contain_the_merge_names_nobody(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        visibility,
        "CandidateContainment",
        _contained_walk(
            lambda commit_sha, lineage: ContainmentVerdict(state=NOT_CONTAINED)
        ),
    )
    with test_database() as conn:
        _open_item(conn)
        _executing_stage(conn)
        conn.commit()
        items = live_visible_items(
            conn,
            {
                "id": "run-stage",
                "project_id": PROJECT_ID,
                "status": "executing",
                "release_lineage": LINEAGE,
            },
        )

    assert items == []


def test_a_succeeded_run_is_not_a_live_visibility_join(monkeypatch) -> None:
    monkeypatch.setattr(visibility, "CandidateContainment", _ForbiddenWalk)
    with test_database() as conn:
        _open_item(conn)
        insert_deployment_run(
            conn,
            id="run-done",
            project_id=PROJECT_ID,
            status="succeeded",
            flow=FLOW,
            target_tier="persistent",
            release_lineage=LINEAGE,
            target_environment_id=ENVIRONMENT_ID,
            completed_at=COMPLETED,
        )
        conn.commit()
        items = live_visible_items(
            conn,
            {
                "id": "run-done",
                "project_id": PROJECT_ID,
                "status": "succeeded",
                "release_lineage": LINEAGE,
            },
        )

    assert items == []


def test_an_in_flight_stage_run_is_not_counted_as_deployed(monkeypatch) -> None:
    from yoke_core.domain import release_delivery_summary as summary_module

    monkeypatch.setattr(summary_module, "CandidateContainment", _ForbiddenWalk)
    with test_database() as conn:
        _open_item(conn)
        _executing_stage(conn)
        conn.commit()
        merges = recorded_merge_shas_for_items(conn, [ITEM_ID]).get(ITEM_ID, ())
        result = delivery_summary(
            merges=merges,
            candidates=ReleaseCandidates(
                conn,
                project_id=PROJECT_ID,
                environment_id=ENVIRONMENT_ID,
                flow=PROD_FLOW,
            ),
            item_id=ITEM_ID,
        )

    assert (result.merges, result.deployed, result.not_deployed) == (1, 0, 1)


def test_list_presentation_joins_contained_items_only_when_members_are_empty(
    monkeypatch,
) -> None:
    from yoke_core.domain.deployment_run_list_read import present_deployment_runs

    monkeypatch.setattr(
        "yoke_core.domain.deployment_run_list_read._member_items",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        "yoke_core.domain.deployment_run_list_read.run_gates",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        "yoke_core.domain.deployment_run_list_read.live_visible_items",
        lambda *_args, **_kwargs: [{"id": ITEM_ID}],
    )
    rows = present_deployment_runs(
        object(),
        [{
            "id": "run-stage",
            "status": "executing",
            "project_id": PROJECT_ID,
            "stages": "[]",
        }],
        actor_id=None,
        visible_project_ids=None,
        include_carried_work=False,
    )

    assert rows[0]["member_items"] == []
    assert rows[0]["contained_items"] == [{"id": ITEM_ID}]


def test_list_presentation_does_not_join_contained_items_over_members(
    monkeypatch,
) -> None:
    from yoke_core.domain.deployment_run_list_read import present_deployment_runs

    monkeypatch.setattr(
        "yoke_core.domain.deployment_run_list_read._member_items",
        lambda *_args, **_kwargs: {
            "run-prod": [{
                "id": ITEM_ID,
                "ref": "YOK-1",
                "title": "prod member",
                "status": "release",
                "project_id": PROJECT_ID,
                "project_sequence": 1,
                "project": "yoke",
            }],
        },
    )
    monkeypatch.setattr(
        "yoke_core.domain.deployment_run_list_read.run_gates",
        lambda *_args, **_kwargs: {},
    )

    def _must_not_look(*_args, **_kwargs):
        raise AssertionError("members already join the card")

    monkeypatch.setattr(
        "yoke_core.domain.deployment_run_list_read.live_visible_items",
        _must_not_look,
    )
    rows = present_deployment_runs(
        object(),
        [{
            "id": "run-prod",
            "status": "executing",
            "project_id": PROJECT_ID,
            "stages": "[]",
        }],
        actor_id=None,
        visible_project_ids=None,
        include_carried_work=False,
    )

    assert rows[0]["member_items"][0]["id"] == ITEM_ID
    assert rows[0]["contained_items"] == []
