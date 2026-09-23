"""Persisted candidate containment is a card join, never membership."""

from __future__ import annotations

from runtime.api.fixtures.backlog_inserts import insert_deployment_run, insert_item
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import deployment_run_contained_items as containment_module
from yoke_core.domain.deployment_run_candidate_containment import (
    CONTAINED,
    NOT_CONTAINED,
    ContainmentVerdict,
)
from yoke_core.domain.deployment_run_contained_items import (
    parse_candidate_containment,
)
from yoke_core.domain.deployment_runs_crud_mutate import cmd_update
from yoke_core.domain.item_merge_receipt_document import record_entry
from yoke_core.domain.json_helper import dumps_compact
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


class _ForbiddenWalk:
    def __init__(self, *args, **kwargs):
        raise AssertionError("list reads must not perform an ancestry walk")


def _contained_walk(answer):
    class _Walk:
        def __init__(self, conn, project_id, *, candidate_lineage):
            self._lineage = candidate_lineage

        def contains(self, commit_sha):
            return answer(commit_sha, self._lineage)

    return _Walk


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
    record_entry(
        conn,
        item_id=ITEM_ID,
        branch=f"LANE-{ITEM_ID}",
        target="main",
        commit_sha=MERGE,
        merge_sha=MERGE,
    )


def _stage_run(conn, *, status: str = "created") -> None:
    insert_deployment_run(
        conn,
        id="run-stage",
        project_id=PROJECT_ID,
        status=status,
        flow=FLOW,
        target_tier="persistent",
        release_lineage=LINEAGE,
        target_environment_id=ENVIRONMENT_ID,
        current_stage="item-qa",
    )


def _member_count(conn) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM deployment_run_items WHERE run_id=%s",
        ("run-stage",),
    ).fetchone()
    return int(row["n"])


def test_start_persists_candidate_containment_without_taking_custody(
    monkeypatch,
) -> None:
    seen: list[str] = []

    def answer(commit_sha, lineage):
        seen.append(commit_sha)
        assert lineage == LINEAGE
        return ContainmentVerdict(state=CONTAINED)

    monkeypatch.setattr(
        containment_module, "CandidateContainment", _contained_walk(answer)
    )
    with test_database() as conn:
        _open_item(conn)
        _stage_run(conn)

        assert cmd_update("run-stage", "status", "executing") is None

        row = conn.execute(
            "SELECT status,candidate_containment FROM deployment_runs WHERE id=%s",
            ("run-stage",),
        ).fetchone()
        snapshot = parse_candidate_containment(row["candidate_containment"])
        members = _member_count(conn)

    assert row["status"] == "executing"
    assert snapshot["derivation"]["contents_known"] is True
    assert snapshot["items"] == [{"id": ITEM_ID, "project_id": PROJECT_ID}]
    assert seen == [MERGE]
    assert members == 0


def test_start_persists_known_empty_containment(monkeypatch) -> None:
    monkeypatch.setattr(
        containment_module,
        "CandidateContainment",
        _contained_walk(
            lambda commit_sha, lineage: ContainmentVerdict(state=NOT_CONTAINED)
        ),
    )
    with test_database() as conn:
        _open_item(conn)
        _stage_run(conn)

        assert cmd_update("run-stage", "status", "executing") is None

        row = conn.execute(
            "SELECT candidate_containment FROM deployment_runs WHERE id=%s",
            ("run-stage",),
        ).fetchone()
        snapshot = parse_candidate_containment(row["candidate_containment"])

    assert snapshot["derivation"] == {
        "status": "known",
        "contents_known": True,
    }
    assert snapshot["items"] == []


def _present(base, monkeypatch):
    from yoke_core.domain.deployment_run_list_read import present_deployment_runs

    monkeypatch.setattr(
        "yoke_core.domain.deployment_run_list_read._member_items",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        "yoke_core.domain.deployment_run_list_read.run_gates",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(containment_module, "CandidateContainment", _ForbiddenWalk)
    return present_deployment_runs(
        object(),
        [base],
        actor_id=None,
        visible_project_ids=None,
        include_carried_work=False,
    )[0]


def test_list_presentation_reads_the_persisted_snapshot_without_network(
    monkeypatch,
) -> None:
    snapshot = {
        "schema": 1,
        "derivation": {"status": "known", "contents_known": True},
        "items": [{"id": ITEM_ID, "project_id": PROJECT_ID}],
    }
    row = _present(
        {
            "id": "run-stage",
            "status": "executing",
            "project_id": PROJECT_ID,
            "candidate_containment": dumps_compact(snapshot),
            "stages": "[]",
        },
        monkeypatch,
    )

    assert row["contained_items"] == snapshot["items"]
    assert "candidate_containment" not in row


def test_terminal_run_does_not_project_the_start_time_join(monkeypatch) -> None:
    snapshot = {
        "schema": 1,
        "derivation": {"status": "known", "contents_known": True},
        "items": [{"id": ITEM_ID, "project_id": PROJECT_ID}],
    }
    row = _present(
        {
            "id": "run-stage",
            "status": "succeeded",
            "project_id": PROJECT_ID,
            "candidate_containment": dumps_compact(snapshot),
            "stages": "[]",
        },
        monkeypatch,
    )

    assert row["contained_items"] == []


def test_an_in_flight_stage_run_is_not_counted_as_deployed(monkeypatch) -> None:
    from yoke_core.domain import release_delivery_summary as summary_module

    monkeypatch.setattr(summary_module, "CandidateContainment", _ForbiddenWalk)
    with test_database() as conn:
        _open_item(conn)
        _stage_run(conn, status="executing")
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
