"""Conflict surveys ignore only proven render-output false positives."""

from __future__ import annotations

import pytest

from runtime.api.domain.path_claim_task_test_support import (
    seed_item_claim,
    seed_target,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.agents_render_path_context import set_render_relationship
from yoke_core.domain.conflict_survey import (
    record_conflict_survey,
    survey_conflicts,
)
from yoke_core.domain.path_claims_overlap_survey import survey_overlaps
from yoke_core.domain.schema_init_path_tables import create_path_registry_tables


RENDERED = "docs/atlas.md"
SOURCE_A = "packages/yoke-core/src/yoke_core/domain/agents_render.py"
SOURCE_B = "packages/yoke-core/src/yoke_core/domain/schema_api_context_render.py"
PARTIAL = "AGENTS.md"


@pytest.fixture
def conn(test_db):
    create_path_registry_tables(test_db)
    test_db.commit()
    return test_db


def _insert_pair(
    conn,
    *,
    candidate_id: int,
    blocker_id: int,
    paths: list[str],
    blocker_workflow: str = "issue",
):
    insert_item(conn, id=candidate_id, workflow_id="dash")
    budget = "\n".join(f"- `{path}`" for path in paths)
    insert_item(
        conn,
        id=blocker_id,
        workflow_id=blocker_workflow,
        spec=f"## File Budget\n\n{budget}\n",
    )


def _register_render_relationship(conn, *, item_id: int) -> dict[str, int]:
    target_ids = {
        path: seed_target(conn, item_id=item_id, path=path)
        for path in (RENDERED, SOURCE_A, SOURCE_B)
    }
    set_render_relationship(
        conn,
        target_path=RENDERED,
        source_paths=[SOURCE_A, SOURCE_B],
        recorded_event_id="render-target-survey-test",
    )
    conn.commit()
    return target_ids


def test_survey_skips_render_target_overlap_with_disjoint_seeds(conn):
    candidate_id, blocker_id = 2310, 2311
    _insert_pair(
        conn,
        candidate_id=candidate_id,
        blocker_id=blocker_id,
        paths=[RENDERED, SOURCE_B],
    )
    targets = _register_render_relationship(conn, item_id=blocker_id)
    seed_item_claim(
        conn,
        item_id=blocker_id,
        target_ids=(targets[RENDERED], targets[SOURCE_B]),
    )

    survey = survey_conflicts(
        conn,
        item_id=candidate_id,
        touch_paths=[RENDERED, SOURCE_A],
    )

    assert survey.clear is True
    assert survey.blockers == ()


def test_survey_keeps_render_target_overlap_with_shared_seed(conn):
    candidate_id, blocker_id = 2320, 2321
    _insert_pair(
        conn,
        candidate_id=candidate_id,
        blocker_id=blocker_id,
        paths=[RENDERED, SOURCE_A],
    )
    targets = _register_render_relationship(conn, item_id=blocker_id)
    seed_item_claim(
        conn,
        item_id=blocker_id,
        target_ids=(targets[RENDERED], targets[SOURCE_A]),
    )

    survey = survey_conflicts(
        conn,
        item_id=candidate_id,
        touch_paths=[RENDERED, SOURCE_A],
    )

    assert survey.clear is False
    assert any(
        blocker.owner_item_id == blocker_id and blocker.path == RENDERED
        for blocker in survey.blockers
    )


def test_survey_keeps_unregistered_partial_generation_overlap(conn):
    candidate_id, blocker_id = 2330, 2331
    _insert_pair(
        conn,
        candidate_id=candidate_id,
        blocker_id=blocker_id,
        paths=[PARTIAL],
    )
    partial_target = seed_target(conn, item_id=blocker_id, path=PARTIAL)
    seed_item_claim(
        conn,
        item_id=blocker_id,
        target_ids=(partial_target,),
    )

    survey = survey_conflicts(
        conn,
        item_id=candidate_id,
        touch_paths=[PARTIAL],
    )

    assert survey.clear is False
    assert any(blocker.path == PARTIAL for blocker in survey.blockers)


def test_claim_advisory_skips_recorded_render_target_overlap(conn):
    candidate_id, blocker_id = 2340, 2341
    _insert_pair(
        conn,
        candidate_id=candidate_id,
        blocker_id=blocker_id,
        paths=[SOURCE_B],
        blocker_workflow="dash",
    )
    targets = _register_render_relationship(conn, item_id=blocker_id)
    recorded = survey_conflicts(
        conn,
        item_id=blocker_id,
        touch_paths=[RENDERED, SOURCE_B],
    )
    record_conflict_survey(conn, recorded)

    overlaps = survey_overlaps(
        conn,
        target_ids=[targets[RENDERED], targets[SOURCE_A]],
        integration_target="main",
        candidate_item_id=candidate_id,
    )

    assert overlaps == []
