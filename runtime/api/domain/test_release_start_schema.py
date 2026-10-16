"""A release driver converges its additive schema before its run starts.

The database is left on the previous release's schema — one additive column
the start path writes is missing — and the candidate driver starts a run
against it in-process, the way ``yoke --env prod-db-admin watch deploy`` does.
"""

from __future__ import annotations

import pytest

from runtime.api.domain.test_deploy_pipeline_admin_bootstrap import (
    _bootstrap_admin_env,
)
from runtime.api.domain.test_deploy_pipeline_https_execution import (
    FLOW,
    LINEAGE,
    PROJECT,
    _invoke,
    _replace_flow,
    serving_plane,  # noqa: F401 - pytest fixture re-export
)
from yoke_core.domain import db_helpers, deploy_pipeline
from yoke_core.domain.release_start_schema import (
    LOCK_UNAVAILABLE,
    ReleaseStartSchemaError,
    converge_release_start_schema,
)
from yoke_core.domain.schema_common import _column_exists

_PREVIOUS_RELEASE_GAP = ("deployment_runs", "current_stage_entered_at")


def _start_previous_schema_run(plane, monkeypatch) -> str:
    conn = plane["conn"]
    _replace_flow(
        conn,
        [
            {"name": "bootstrap", "step_runner": "auto", "qa_kind": "bootstrap"},
            {"name": "complete", "step_runner": "auto"},
        ],
    )
    _bootstrap_admin_env(monkeypatch, plane)
    run_id = str(
        _invoke(
            "deployment_runs.create",
            {"project": PROJECT, "flow": FLOW, "release_lineage": LINEAGE},
        )["run_id"]
    )
    table, column = _PREVIOUS_RELEASE_GAP
    conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
    conn.commit()
    assert not _column_exists(conn, table, column)
    return run_id


def test_release_start_adds_the_missing_column_before_admission(
    serving_plane,  # noqa: F811 - fixture re-export, this is the intended shadow
    monkeypatch,
) -> None:
    run_id = _start_previous_schema_run(serving_plane, monkeypatch)

    assert deploy_pipeline.run_pipeline(run_id) == deploy_pipeline.EXIT_SUCCESS
    assert _column_exists(serving_plane["conn"], *_PREVIOUS_RELEASE_GAP)


def test_busy_table_refuses_by_name_and_starts_nothing(
    serving_plane,  # noqa: F811 - fixture re-export, this is the intended shadow
    monkeypatch,
) -> None:
    run_id = _start_previous_schema_run(serving_plane, monkeypatch)
    holder = db_helpers.connect()
    try:
        holder.execute("LOCK TABLE deployment_runs IN ACCESS SHARE MODE")
        with pytest.raises(ReleaseStartSchemaError) as refused:
            converge_release_start_schema(run_id)
    finally:
        holder.rollback()
        holder.close()

    assert refused.value.code == LOCK_UNAVAILABLE
    assert f"yoke watch deploy -- {run_id}" in str(refused.value)
    status = (
        serving_plane["conn"]
        .execute("SELECT status FROM deployment_runs WHERE id=%s", (run_id,))
        .fetchone()[0]
    )
    assert status == "created"


def test_https_driver_leaves_the_schema_to_the_serving_build(monkeypatch) -> None:
    from yoke_cli.transport import https as https_transport

    monkeypatch.setattr(
        https_transport, "resolve_https_connection", lambda *_a, **_k: object()
    )
    monkeypatch.setattr(
        db_helpers,
        "connect",
        lambda *_a, **_k: pytest.fail("an HTTPS driver opened the database"),
    )
    assert converge_release_start_schema("run-https") is False
