"""Regression tests for done-transition preconditions: AC-3, AC-4, AC-5.

Latest deploy_run not failed.
Epic refined_idea_to_planning verdict required.
No-run-delivery flow bypass.

Plus short-circuit cases for empty / internal / unregistered flows.
AC-1 and AC-2 (deployed_to and deploy_stage) live in the sibling
``test_done_transition_preconditions`` module to fit the 350-line cap.
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


def _seed_registered_flow(db_path, flow_id="yoke-prod-release", project="yoke"):
    conn = connect_dt_db(db_path)
    p = _p(conn)
    conn.execute(
        f"INSERT INTO deployment_flows (id, project_id, name) VALUES ({p}, {p}, {p})",
        (flow_id, _project_id(project), "Test Flow"),
    )
    conn.commit()
    conn.close()


def _seed_deploy_run(db_path, item_id, status):
    conn = connect_dt_db(db_path)
    run_id = f"r-{item_id}-{status}"
    p = _p(conn)
    conn.execute(
        "INSERT INTO deployment_runs (id, project_id, status, created_at) "
        f"VALUES ({p}, {p}, {p}, {p})",
        (run_id, 1, status, "2025-01-01T00:00:00Z"),
    )
    conn.execute(
        f"INSERT INTO deployment_run_items (run_id, item_id) VALUES ({p}, {p})",
        (run_id, item_id),
    )
    conn.commit()
    conn.close()


def _seed_verdict(db_path, item_id, transition="refined_idea_to_planning", verdict="READY"):
    conn = connect_dt_db(db_path)
    p = _p(conn)
    conn.execute(
        "INSERT INTO shepherd_verdicts (item, transition, worker, verdict, created_at) "
        f"VALUES ({p}, {p}, {p}, {p}, {p})",
        (f"YOK-{item_id}", transition, "architect", verdict, "2025-01-01"),
    )
    conn.commit()
    conn.close()


class TestAC3LatestRunNotFailed:
    """AC-3: latest deploy_run not failed."""

    def test_failed_latest_run_blocks(self, dt_db):
        db_path, _ = dt_db
        _seed_registered_flow(db_path)
        _insert_item(
            db_path,
            721,
            deployment_flow="yoke-prod-release",
            deploy_stage="complete",
            deployed_to="prod",
        )
        _seed_deploy_run(db_path, 721, "failed")

        allowed, reason = check_done_preconditions(
            721, "yoke-prod-release", "issue",
        )

        assert allowed is False
        assert reason == "latest deploy_run for YOK-721 has status=failed"

    def test_succeeded_latest_run_allows(self, dt_db):
        db_path, _ = dt_db
        _seed_registered_flow(db_path)
        _insert_item(
            db_path,
            722,
            deployment_flow="yoke-prod-release",
            deploy_stage="complete",
            deployed_to="prod",
        )
        _seed_deploy_run(db_path, 722, "succeeded")

        allowed, reason = check_done_preconditions(
            722, "yoke-prod-release", "issue",
        )

        assert allowed is True
        assert reason is None

    def test_no_runs_allows(self, dt_db):
        """No deploy_runs row is allowed — other checks gate evidence."""
        db_path, _ = dt_db
        _insert_item(db_path, 723, deployment_flow="", deploy_stage=None)

        allowed, reason = check_done_preconditions(723, "", "issue")

        assert allowed is True
        assert reason is None


class TestAC4EpicVerdictRequired:
    """AC-4: epics need refined_idea_to_planning READY/CAVEATS verdict."""

    def test_missing_verdict_blocks_epic(self, dt_db):
        db_path, _ = dt_db
        _insert_item(db_path, 731, type="epic", deployment_flow="")

        allowed, reason = check_done_preconditions(731, "", "epic")

        assert allowed is False
        assert reason == (
            "epic YOK-731 missing refined_idea_to_planning READY/CAVEATS verdict"
        )

    def test_ready_verdict_allows_epic(self, dt_db):
        db_path, _ = dt_db
        _insert_item(db_path, 732, type="epic", deployment_flow="")
        _seed_verdict(db_path, 732, verdict="READY")

        allowed, reason = check_done_preconditions(732, "", "epic")

        assert allowed is True
        assert reason is None

    def test_caveats_verdict_allows_epic(self, dt_db):
        db_path, _ = dt_db
        _insert_item(db_path, 733, type="epic", deployment_flow="")
        _seed_verdict(db_path, 733, verdict="CAVEATS")

        allowed, reason = check_done_preconditions(733, "", "epic")

        assert allowed is True
        assert reason is None

    def test_blocked_verdict_does_not_satisfy_epic(self, dt_db):
        """A BLOCKED verdict is not READY/CAVEATS — must still block."""
        db_path, _ = dt_db
        _insert_item(db_path, 734, type="epic", deployment_flow="")
        _seed_verdict(db_path, 734, verdict="BLOCKED")

        allowed, reason = check_done_preconditions(734, "", "epic")

        assert allowed is False
        assert reason == (
            "epic YOK-734 missing refined_idea_to_planning READY/CAVEATS verdict"
        )

    def test_issues_do_not_require_verdict(self, dt_db):
        """Issues never need the shepherd verdict — only epics."""
        db_path, _ = dt_db
        _insert_item(db_path, 735, type="issue", deployment_flow="")

        allowed, reason = check_done_preconditions(735, "", "issue")

        assert allowed is True
        assert reason is None


class TestAC5NoRunDeliveryBypass:
    """AC-5: no-run-delivery flow bypasses deployed_to but not AC-2."""

    def test_no_run_delivery_allows_empty_deployed_to(self, dt_db):
        db_path, _ = dt_db
        _insert_item(
            db_path,
            741,
            deployment_flow="no-run-delivery",
            deploy_stage="complete",
            deployed_to=None,
        )

        allowed, reason = check_done_preconditions(
            741, "no-run-delivery", "issue",
        )

        assert allowed is True
        assert reason is None

    def test_no_run_delivery_still_requires_deploy_stage(self, dt_db):
        db_path, _ = dt_db
        _insert_item(
            db_path,
            742,
            deployment_flow="no-run-delivery",
            deploy_stage=None,
            deployed_to=None,
        )

        allowed, reason = check_done_preconditions(
            742, "no-run-delivery", "issue",
        )

        assert allowed is False
        assert reason == "deploy_stage is null for deployment_flow=no-run-delivery"


class TestEmptyAndInternalFlows:
    """Empty / internal deployment_flow short-circuits AC-1, AC-2 (no pipeline)."""

    def test_empty_flow_skips_deployed_to_check(self, dt_db):
        db_path, _ = dt_db
        _insert_item(
            db_path,
            751,
            deployment_flow="",
            deploy_stage=None,
            deployed_to=None,
        )

        allowed, reason = check_done_preconditions(751, "", "issue")

        assert allowed is True
        assert reason is None

    def test_internal_flow_skips_deployment_checks(self, dt_db):
        db_path, _ = dt_db
        _seed_registered_flow(db_path, flow_id="yoke-internal", project="yoke")
        _insert_item(
            db_path,
            752,
            deployment_flow="yoke-internal",
            deploy_stage=None,
            deployed_to=None,
        )

        allowed, reason = check_done_preconditions(
            752, "yoke-internal", "issue",
        )

        assert allowed is True
        assert reason is None


class TestUnregisteredFlowSkipped:
    """An unregistered, non-internal flow value does not gate AC-1/AC-2.

    The deployment-flow-guard upstream already rejects unregistered flow
    ids; this module deliberately does not double-fire on the same
    condition — its job is the four named preconditions.
    """

    def test_unregistered_non_internal_flow_does_not_gate(self, dt_db):
        db_path, _ = dt_db
        # No insert into deployment_flows -> flow id is unknown.
        _insert_item(
            db_path,
            761,
            deployment_flow="garbage-flow",
            deploy_stage=None,
            deployed_to=None,
        )

        allowed, reason = check_done_preconditions(
            761, "garbage-flow", "issue",
        )

        assert allowed is True
        assert reason is None
