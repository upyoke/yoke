# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.domain.path_context_test_support import _p as _p

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


def _seed_registered_flow(db_path, flow_id="yoke-hosted-production", project="yoke"):
    conn = connect_dt_db(db_path)
    p = _p(conn)
    conn.execute(
        f"INSERT INTO deployment_flows (id, project_id, name) VALUES ({p}, {p}, {p})",
        (flow_id, _project_id(project), "Test Flow"),
    )
    conn.commit()
    conn.close()


def _seed_deploy_run(
    db_path,
    item_id,
    status,
    flow="yoke-hosted-production",
    created_at="2025-01-01T00:00:00Z",
):
    conn = connect_dt_db(db_path)
    run_id = f"r-{item_id}-{status}-{flow}"
    p = _p(conn)
    conn.execute(
        f"INSERT INTO deployment_runs (id, project_id, flow, status, created_at) "
        f"VALUES ({p}, {p}, {p}, {p}, {p})",
        (run_id, 1, flow, status, created_at),
    )
    conn.execute(
        f"INSERT INTO deployment_run_items (run_id, item_id) VALUES ({p}, {p})",
        (run_id, item_id),
    )
    conn.commit()
    conn.close()
