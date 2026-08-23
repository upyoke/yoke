"""Succeeded deploy-run rows attest delivery when item stamps are empty.

Historic bare-id router misses left ``deployed_to`` / ``deploy_stage``
empty on non-default-project items whose run still succeeded. The
precondition bundle accepts that run as evidence; a failed latest run
still refuses.
"""

from __future__ import annotations

from yoke_core.domain import db_backend
from yoke_core.engines import done_transition  # noqa: F401 — parent registration
from yoke_core.engines.done_transition_preconditions import (
    check_done_preconditions,
)

from runtime.api.engines._done_transition_test_helpers import (
    _insert_item,
    _project_id,
    connect_dt_db,
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


def _seed_deploy_run(db_path, item_id, status, current_stage="complete"):
    conn = connect_dt_db(db_path)
    run_id = f"r-{item_id}-{status}"
    p = _p(conn)
    conn.execute(
        "INSERT INTO deployment_runs "
        "(id, project_id, status, current_stage, created_at) "
        f"VALUES ({p}, {p}, {p}, {p}, {p})",
        (run_id, 1, status, current_stage, "2025-01-01T00:00:00Z"),
    )
    conn.execute(
        f"INSERT INTO deployment_run_items (run_id, item_id) VALUES ({p}, {p})",
        (run_id, item_id),
    )
    conn.commit()
    conn.close()


class TestSucceededRunAttestsEmptyStamps:
    def test_empty_stamps_with_succeeded_run_allows(self, dt_db):
        db_path, _ = dt_db
        _seed_registered_flow(db_path)
        _insert_item(
            db_path,
            801,
            deployment_flow="yoke-hosted-production",
            deploy_stage=None,
            deployed_to=None,
        )
        _seed_deploy_run(db_path, 801, "succeeded")

        allowed, reason = check_done_preconditions(
            801, "yoke-hosted-production", False,
        )

        assert allowed is True
        assert reason is None

    def test_empty_stamps_with_executing_run_still_blocks(self, dt_db):
        db_path, _ = dt_db
        _seed_registered_flow(db_path)
        _insert_item(
            db_path,
            802,
            deployment_flow="yoke-hosted-production",
            deploy_stage=None,
            deployed_to=None,
        )
        _seed_deploy_run(db_path, 802, "executing", current_stage="warm-up")

        allowed, reason = check_done_preconditions(
            802, "yoke-hosted-production", False,
        )

        assert allowed is False
        assert reason == (
            "deployed_to is empty for deployment_flow=yoke-hosted-production"
        )

    def test_failed_run_still_blocks_when_stamps_present(self, dt_db):
        db_path, _ = dt_db
        _seed_registered_flow(db_path)
        _insert_item(
            db_path,
            803,
            deployment_flow="yoke-hosted-production",
            deploy_stage="complete",
            deployed_to="prod",
        )
        _seed_deploy_run(db_path, 803, "failed")

        allowed, reason = check_done_preconditions(
            803, "yoke-hosted-production", False,
        )

        assert allowed is False
        assert "status=failed" in (reason or "")
