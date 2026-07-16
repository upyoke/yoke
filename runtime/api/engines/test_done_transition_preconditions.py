"""Regression tests for done-transition preconditions: AC-1 and AC-2.

deployed_to non-empty when deployment_flow is registered.
deploy_stage non-null when deployment_flow is registered.

AC-3, AC-4, AC-5 and short-circuit cases live in the sibling
``test_done_transition_preconditions_epic_and_runs`` module to fit the
350-line cap.
"""

from __future__ import annotations

from yoke_core.domain import db_backend
from yoke_core.engines import done_transition  # noqa: F401 — parent registration
from yoke_core.engines.done_transition_preconditions import (
    check_done_preconditions,
)

from yoke_core.engines._done_transition_test_helpers import (
    _insert_item,
    _project_id,
    connect_dt_db,
    dt_db,  # noqa: F401 — pytest fixture re-export
)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _seed_registered_flow(db_path, flow_id="yoke-hosted-production", project="yoke"):
    conn = connect_dt_db(db_path)
    p = _p(conn)
    conn.execute(
        f"INSERT INTO deployment_flows (id, project_id, name) VALUES ({p}, {p}, {p})",
        (flow_id, _project_id(project), "Test Flow"),
    )
    conn.commit()
    conn.close()


class TestAC1DeployedToRequired:
    """AC-1: registered flow + empty deployed_to refuses with exact reason."""

    def test_empty_deployed_to_blocks_with_exact_reason(self, dt_db):
        db_path, _ = dt_db
        _seed_registered_flow(db_path)
        _insert_item(
            db_path,
            701,
            deployment_flow="yoke-hosted-production",
            deploy_stage="complete",
            deployed_to=None,
        )

        allowed, reason = check_done_preconditions(
            701, "yoke-hosted-production", "issue",
        )

        assert allowed is False
        assert reason == "deployed_to is empty for deployment_flow=yoke-hosted-production"

    def test_non_empty_deployed_to_allows(self, dt_db):
        db_path, _ = dt_db
        _seed_registered_flow(db_path)
        _insert_item(
            db_path,
            702,
            deployment_flow="yoke-hosted-production",
            deploy_stage="complete",
            deployed_to="prod-us-east",
        )

        allowed, reason = check_done_preconditions(
            702, "yoke-hosted-production", "issue",
        )

        assert allowed is True
        assert reason is None

    def test_literal_null_string_treated_as_empty(self, dt_db):
        db_path, _ = dt_db
        _seed_registered_flow(db_path)
        _insert_item(
            db_path,
            703,
            deployment_flow="yoke-hosted-production",
            deploy_stage="complete",
            deployed_to="null",
        )

        allowed, reason = check_done_preconditions(
            703, "yoke-hosted-production", "issue",
        )

        assert allowed is False
        assert reason == "deployed_to is empty for deployment_flow=yoke-hosted-production"


class TestAC2DeployStageRequired:
    """AC-2: registered flow + null deploy_stage refuses."""

    def test_null_deploy_stage_blocks(self, dt_db):
        db_path, _ = dt_db
        _seed_registered_flow(db_path)
        _insert_item(
            db_path,
            711,
            deployment_flow="yoke-hosted-production",
            deploy_stage=None,
            deployed_to="prod",
        )

        allowed, reason = check_done_preconditions(
            711, "yoke-hosted-production", "issue",
        )

        assert allowed is False
        assert reason == "deploy_stage is null for deployment_flow=yoke-hosted-production"

    def test_non_null_deploy_stage_allows(self, dt_db):
        db_path, _ = dt_db
        _seed_registered_flow(db_path)
        _insert_item(
            db_path,
            712,
            deployment_flow="yoke-hosted-production",
            deploy_stage="complete",
            deployed_to="prod",
        )

        allowed, reason = check_done_preconditions(
            712, "yoke-hosted-production", "issue",
        )

        assert allowed is True
        assert reason is None
