"""Path-claim registration must see a live survey's declared paths.

Claim classification compares claim membership, so an item registering a
claim was blind to a direct-workflow item that had declared the same edit
targets without a claim of its own. Visibility now runs both ways.
"""

from __future__ import annotations

import pytest

from runtime.api.domain.path_claim_task_test_support import seed_target
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.conflict_survey import record_conflict_survey, survey_conflicts
from yoke_core.domain.path_claims import IncompatibleOverlap, register

SURVEYED_PATH = "src/declared_by_a_dash.py"


def _seed_survey(conn, *, item_id, paths=(SURVEYED_PATH,), status=None, frozen=0):
    insert_item(
        conn,
        id=item_id,
        workflow_id="dash",
        frozen=frozen,
        **({"status": status} if status else {}),
    )
    record_conflict_survey(
        conn, survey_conflicts(conn, item_id=item_id, touch_paths=list(paths)),
    )


def _register_over(conn, *, item_id, path=SURVEYED_PATH):
    insert_item(conn, id=item_id, workflow_id="issue")
    return register(
        conn,
        actor_id=seed_human_actor(conn),
        integration_target="main",
        target_ids=[seed_target(conn, item_id=item_id, path=path)],
        item_id=item_id,
        candidate_item_id=item_id,
    )


def _link(conn, *, dependent_item_id, blocking_item_id, gate_point, rationale):
    conn.execute(
        "INSERT INTO item_dependencies "
        "(dependent_item_id, blocking_item_id, gate_point, satisfaction, "
        "source, rationale, created_at) "
        "VALUES (%s, %s, %s, 'fact:merged', 'test', %s, "
        "'2026-08-20T00:00:00Z')",
        (dependent_item_id, blocking_item_id, gate_point, rationale),
    )
    conn.commit()


class TestSurveyBlocksRegistration:
    def test_registration_over_a_declared_survey_path_is_refused(self, test_db):
        _seed_survey(test_db, item_id=2260)

        with pytest.raises(IncompatibleOverlap) as refusal:
            _register_over(test_db, item_id=2261)

        message = str(refusal.value)
        assert "Conflict Survey" in message
        assert SURVEYED_PATH in message
        assert "declared intent rather than a registered claim" in message

    def test_disjoint_coverage_still_registers(self, test_db):
        _seed_survey(test_db, item_id=2262)

        claim_id = _register_over(
            test_db, item_id=2263, path="src/somewhere_else.py",
        )

        assert claim_id > 0

    def test_survey_on_another_integration_target_does_not_refuse(self, test_db):
        insert_item(test_db, id=2264, workflow_id="dash")
        record_conflict_survey(
            test_db,
            survey_conflicts(
                test_db,
                item_id=2264,
                touch_paths=[SURVEYED_PATH],
                integration_target="release/2026.01",
            ),
        )

        assert _register_over(test_db, item_id=2265) > 0

    def test_terminal_and_frozen_surveys_are_dormant(self, test_db):
        _seed_survey(test_db, item_id=2266, status="done")
        _seed_survey(test_db, item_id=2267, frozen=1, paths=("src/parked.py",))

        assert _register_over(test_db, item_id=2268) > 0
        assert _register_over(test_db, item_id=2269, path="src/parked.py") > 0


class TestDeclaredEdgesDecideDirection:
    def test_coordination_only_edge_allows_registration(self, test_db):
        _seed_survey(test_db, item_id=2270)
        insert_item(test_db, id=2271, workflow_id="issue")
        _link(
            test_db,
            dependent_item_id=2271,
            blocking_item_id=2270,
            gate_point="coordination_only",
            rationale=(
                f"decision=coordination_only. shared_paths={SURVEYED_PATH}. "
                "independence_evidence=disjoint functions"
            ),
        )

        claim_id = register(
            test_db,
            actor_id=seed_human_actor(test_db),
            integration_target="main",
            target_ids=[seed_target(test_db, item_id=2271, path=SURVEYED_PATH)],
            item_id=2271,
            candidate_item_id=2271,
        )

        assert claim_id > 0

    def test_candidate_as_dependent_registers_blocked(self, test_db):
        _seed_survey(test_db, item_id=2272)
        insert_item(test_db, id=2273, workflow_id="issue")
        _link(
            test_db,
            dependent_item_id=2273,
            blocking_item_id=2272,
            gate_point="activation",
            rationale="declared survey lands first",
        )

        claim_id = register(
            test_db,
            actor_id=seed_human_actor(test_db),
            integration_target="main",
            target_ids=[seed_target(test_db, item_id=2273, path=SURVEYED_PATH)],
            item_id=2273,
            candidate_item_id=2273,
        )

        state = test_db.execute(
            "SELECT state FROM path_claims WHERE id = %s", (claim_id,),
        ).fetchone()[0]
        assert state == "blocked"

    def test_candidate_as_blocker_does_not_wait(self, test_db):
        _seed_survey(test_db, item_id=2274)
        insert_item(test_db, id=2275, workflow_id="issue")
        _link(
            test_db,
            dependent_item_id=2274,
            blocking_item_id=2275,
            gate_point="activation",
            rationale="registering claim lands first",
        )

        claim_id = register(
            test_db,
            actor_id=seed_human_actor(test_db),
            integration_target="main",
            target_ids=[seed_target(test_db, item_id=2275, path=SURVEYED_PATH)],
            item_id=2275,
            candidate_item_id=2275,
        )

        state = test_db.execute(
            "SELECT state FROM path_claims WHERE id = %s", (claim_id,),
        ).fetchone()[0]
        assert state == "planned"
