"""Survey declarations advise while registered claims keep the door lock."""

from __future__ import annotations

from contextlib import nullcontext

import pytest

from runtime.api.domain.path_claim_task_test_support import (
    seed_item_claim,
    seed_target,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import claims_path as claims_path_handler
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.conflict_survey import record_conflict_survey, survey_conflicts
from yoke_core.domain.path_claims import (
    IncompatibleOverlap,
    activate,
    register,
)
from yoke_core.domain.path_claims_lineage import expand_lineage
from yoke_core.domain.path_claims_overlap_survey import (
    SURVEY_ADVISORY_PROCEED,
    SURVEY_ADVISORY_YIELD,
    survey_overlaps,
)

SURVEYED_PATH = "src/declared_by_a_dash.py"


@pytest.fixture(autouse=True)
def _no_render_target_context(monkeypatch):
    monkeypatch.setattr(
        "yoke_core.domain.agents_render_path_context.read_render_source_for",
        lambda *_args, **_kwargs: None,
    )


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


def _register(conn, *, item_id, target_id):
    return register(
        conn,
        actor_id=seed_human_actor(conn),
        integration_target="main",
        target_ids=[target_id],
        item_id=item_id,
        candidate_item_id=item_id,
    )


def _link_coordination(conn, *, candidate_item_id, blocker_item_id, path):
    conn.execute(
        "INSERT INTO item_dependencies "
        "(dependent_item_id, blocking_item_id, gate_point, satisfaction, "
        "source, rationale, created_at) "
        "VALUES (%s, %s, 'coordination_only', 'compatible', 'test', %s, "
        "'2026-08-20T00:00:00Z')",
        (
            candidate_item_id,
            blocker_item_id,
            f"decision=coordination_only. shared_paths={path}. "
            "independence_evidence=disjoint functions",
        ),
    )
    conn.commit()


def _set_parent(conn, *, child_id, parent_id):
    conn.execute(
        "UPDATE path_targets SET parent_target_id = %s WHERE id = %s",
        (parent_id, child_id),
    )
    conn.commit()


class TestSurveyAdvisory:
    def test_overlap_reports_routes_but_registers_and_activates(
        self, test_db, monkeypatch,
    ):
        _seed_survey(test_db, item_id=2260, status="implementing")
        insert_item(test_db, id=2261, workflow_id="issue")
        seed_target(test_db, item_id=2261, path=SURVEYED_PATH)
        actor_id = seed_human_actor(test_db)
        monkeypatch.setattr(
            claims_path_handler, "_connect_rw", lambda: nullcontext(test_db),
        )
        outcome = claims_path_handler.handle_register(FunctionCallRequest(
            function="claims.path.register",
            actor=ActorContext(
                actor_id=str(actor_id), session_id="survey-advisory-test",
            ),
            target=TargetRef(kind="item", item_id=2261),
            payload={
                "actor_id": actor_id,
                "integration_target": "main",
                "paths": [SURVEYED_PATH],
            },
        ))
        assert outcome.primary_success, outcome.error
        claim_id = int(outcome.result_payload["claim_id"])
        advisory = str(outcome.result_payload["advisory"])
        activate(
            test_db, claim_id=claim_id, base_commit_sha="candidate-base",
        )

        assert "YOK-2260 (implementing)" in advisory
        assert repr(SURVEYED_PATH) in advisory
        assert SURVEY_ADVISORY_PROCEED in advisory
        assert SURVEY_ADVISORY_YIELD in advisory
        state = test_db.execute(
            "SELECT state FROM path_claims WHERE id = %s", (claim_id,),
        ).fetchone()[0]
        assert state == "active"

    def test_disjoint_files_under_shared_ancestors_have_no_advisory(self, test_db):
        surveyed = "packages/yoke-core/src/surveyed.py"
        candidate = "packages/yoke-core/src/candidate.py"
        _seed_survey(test_db, item_id=2262, paths=(surveyed,))
        insert_item(test_db, id=2263, workflow_id="issue")
        root_id = seed_target(
            test_db, item_id=2263, path="packages", kind="directory",
        )
        package_id = seed_target(
            test_db,
            item_id=2263,
            path="packages/yoke-core",
            kind="directory",
        )
        target_id = seed_target(test_db, item_id=2263, path=candidate)
        _set_parent(test_db, child_id=package_id, parent_id=root_id)
        _set_parent(test_db, child_id=target_id, parent_id=package_id)

        assert {root_id, package_id, target_id} <= set(
            expand_lineage(test_db, [target_id])
        )
        assert survey_overlaps(
            test_db,
            target_ids=[target_id],
            integration_target="main",
            candidate_item_id=2263,
        ) == []
        assert _register(test_db, item_id=2263, target_id=target_id) > 0

    def test_terminal_and_frozen_surveys_are_dormant(self, test_db):
        _seed_survey(test_db, item_id=2264, status="done")
        _seed_survey(test_db, item_id=2265, frozen=1)
        insert_item(test_db, id=2266, workflow_id="issue")
        target_id = seed_target(test_db, item_id=2266, path=SURVEYED_PATH)

        assert survey_overlaps(
            test_db,
            target_ids=[target_id],
            integration_target="main",
            candidate_item_id=2266,
        ) == []

    def test_claim_without_an_owning_item_consults_no_survey(self, test_db):
        _seed_survey(test_db, item_id=2267)
        insert_item(test_db, id=2268, workflow_id="issue")
        target_id = seed_target(test_db, item_id=2268, path=SURVEYED_PATH)

        assert survey_overlaps(
            test_db,
            target_ids=[target_id],
            integration_target="main",
            candidate_item_id=None,
        ) == []


class TestClaimDoorLock:
    def test_same_target_claim_still_blocks(self, test_db):
        insert_item(test_db, id=2280, workflow_id="issue")
        insert_item(test_db, id=2281, workflow_id="issue")
        target_id = seed_target(test_db, item_id=2280, path="src/shared.py")
        seed_item_claim(
            test_db, item_id=2280, target_ids=(target_id,), state="active",
        )

        with pytest.raises(IncompatibleOverlap, match="active claim"):
            _register(test_db, item_id=2281, target_id=target_id)

    def test_coordination_only_claims_activate_in_parallel(self, test_db):
        path = "src/coordinated.py"
        insert_item(test_db, id=2282, workflow_id="issue")
        insert_item(test_db, id=2283, workflow_id="issue")
        target_id = seed_target(test_db, item_id=2282, path=path)
        seed_item_claim(
            test_db, item_id=2282, target_ids=(target_id,), state="active",
        )
        _link_coordination(
            test_db,
            candidate_item_id=2283,
            blocker_item_id=2282,
            path=path,
        )

        claim_id = _register(test_db, item_id=2283, target_id=target_id)
        activate(test_db, claim_id=claim_id, base_commit_sha="coordinated-base")

        state = test_db.execute(
            "SELECT state FROM path_claims WHERE id = %s", (claim_id,),
        ).fetchone()[0]
        assert state == "active"

    def test_ancestor_claim_still_blocks_descendant_claim(self, test_db):
        insert_item(test_db, id=2284, workflow_id="issue")
        insert_item(test_db, id=2285, workflow_id="issue")
        directory_id = seed_target(
            test_db, item_id=2284, path="src", kind="directory",
        )
        file_id = seed_target(test_db, item_id=2285, path="src/nested.py")
        _set_parent(test_db, child_id=file_id, parent_id=directory_id)
        seed_item_claim(
            test_db, item_id=2284, target_ids=(directory_id,), state="active",
        )

        with pytest.raises(IncompatibleOverlap):
            _register(test_db, item_id=2285, target_id=file_id)
