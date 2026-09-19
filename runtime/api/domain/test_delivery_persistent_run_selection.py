"""Which runs stand in for the flow when an item stores none.

An item with no stored deployment flow is answered by containment over its
own project's releases. This pins which releases that walk is allowed to
ask about: succeeded, this project's, and bound for a destination that
outlives the run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.fixtures.backlog_inserts import (
    _ensure_project_id,
    insert_deployment_run,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_core.domain.delivery_release_candidates import (
    succeeded_persistent_runs,
)


def _apply_deploy_schema() -> None:
    from yoke_core.domain import deployment_runs_schema, schema
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.project_seed_test_helpers import seed_project_identities

    schema.cmd_init()
    conn = connect()
    try:
        seed_project_identities(conn)
    finally:
        conn.close()
    deployment_runs_schema.cmd_init()


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path, _apply_deploy_schema) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


def _project_id(conn, project: str) -> int:
    return int(_ensure_project_id(conn, project, ts="2026-01-01T00:00:00Z"))


def _environment_id(conn, project_id: int, name: str) -> int:
    """A registered environment, which a persistent run is required to name."""
    conn.execute(
        "INSERT INTO sites(project_id,name,created_at) "
        "VALUES (%s,%s,'2026-01-01T00:00:00Z')",
        (project_id, f"site-{project_id}"),
    )
    conn.execute(
        "INSERT INTO environments(site,project_id,name,created_at) "
        "SELECT id,%s,%s,'2026-01-01T00:00:00Z' FROM sites "
        "WHERE project_id=%s AND name=%s",
        (project_id, name, project_id, f"site-{project_id}"),
    )
    return int(
        conn.execute(
            "SELECT id FROM environments WHERE project_id=%s AND name=%s",
            (project_id, name),
        ).fetchone()[0]
    )


def _run(conn, run_id: str, *, environment_id=None, **kwargs):
    defaults = {
        "status": "succeeded",
        "target_tier": "persistent",
        "release_lineage": f"lineage-{run_id}",
        "completed_at": "2026-01-01T00:00:00Z",
    }
    defaults.update(kwargs)
    if defaults["target_tier"] == "persistent":
        # The schema pairs the two: a persistent run always names the
        # environment it reached, and an ephemeral one never does.
        defaults["target_environment_id"] = environment_id
    insert_deployment_run(conn, id=run_id, **defaults)


def test_only_succeeded_persistent_runs_of_this_project_are_asked(db):
    conn = connect_test_db(db)
    try:
        project_id = _project_id(conn, "yoke")
        home = _environment_id(conn, project_id, "prod")
        elsewhere_project = _project_id(conn, "platform")
        elsewhere = _environment_id(conn, elsewhere_project, "prod")
        _run(conn, "run-carrier", flow="prod-flow", environment_id=home)
        _run(conn, "run-preview", flow="preview-flow", target_tier="ephemeral")
        _run(
            conn, "run-failed", flow="prod-flow", status="failed",
            environment_id=home,
        )
        _run(
            conn, "run-elsewhere", project="platform", flow="platform-flow",
            environment_id=elsewhere,
        )
        conn.commit()
        releases = succeeded_persistent_runs(conn, project_id=project_id)
    finally:
        conn.close()
    assert [release["id"] for release in releases] == ["run-carrier"]
    assert releases[0]["release_lineage"] == "lineage-run-carrier"


def test_any_flow_of_this_project_qualifies(db):
    """Standing in for the flow means the flow no longer narrows the walk."""
    conn = connect_test_db(db)
    try:
        project_id = _project_id(conn, "yoke")
        home = _environment_id(conn, project_id, "prod")
        _run(
            conn, "run-a", flow="prod-flow", environment_id=home,
            completed_at="2026-01-02T00:00:00Z",
        )
        _run(
            conn, "run-b", flow="hotfix-flow", environment_id=home,
            completed_at="2026-01-03T00:00:00Z",
        )
        conn.commit()
        releases = succeeded_persistent_runs(conn, project_id=project_id)
    finally:
        conn.close()
    # Newest first: the newest release contains the most merges.
    assert [release["id"] for release in releases] == ["run-b", "run-a"]
