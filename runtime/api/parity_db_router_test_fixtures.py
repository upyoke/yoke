"""Shared schema, helpers, and the ``item_query_env`` / ``parity_env`` fixtures
for the parity db_router + render test sibling modules. Imported, not
pytest-collected."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from yoke_core.domain import db_backend
from runtime.api.fixtures.file_test_db import apply_inline_ddl, init_test_db
from runtime.api.fixtures.schema_ddl_items import _ITEMS_DDL


_LARGE_SPEC_TEXT = "This is a large spec text. " * 500  # ~13KB


# Items-table DDL is sourced from canonical schema init via
# ``_ITEMS_DDL`` so future column additions land here automatically.
# The deployment-domain tables and ``item_progress_view`` below remain
# fixture-local because they are exercised only by these parity tests.
# Tables precede the view that references them: Postgres validates a view's
# referenced relations at CREATE time (SQLite is lazy), so deployment_flows /
# deployment_runs / deployment_run_items must exist before item_progress_view.
_ITEM_QUERY_SCHEMA = """
CREATE TABLE projects (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    github_repo TEXT,
    public_item_prefix TEXT NOT NULL DEFAULT 'YOK',
    created_at TEXT NOT NULL DEFAULT ''
);
""" + _ITEMS_DDL + """
CREATE TABLE deployment_flows (
    id TEXT PRIMARY KEY,
    project_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    stages TEXT NOT NULL,
    on_failure TEXT DEFAULT 'halt',
    created_at TEXT NOT NULL DEFAULT '',
    target_env TEXT DEFAULT NULL,
    done_description TEXT DEFAULT NULL,
    UNIQUE(project_id, name)
);

CREATE TABLE deployment_runs (
    id TEXT PRIMARY KEY,
    project_id INTEGER NOT NULL,
    flow TEXT NOT NULL,
    target_env TEXT,
    release_lineage TEXT,
    status TEXT NOT NULL DEFAULT 'created'
      CHECK(status IN ('created','executing','succeeded','failed','cancelled')),
    current_stage TEXT,
    created_at TEXT NOT NULL DEFAULT '',
    started_at TEXT,
    completed_at TEXT,
    created_by TEXT DEFAULT 'operator'
);

CREATE TABLE deployment_run_items (
    run_id TEXT NOT NULL,
    item_id INTEGER NOT NULL,
    added_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (run_id, item_id)
);

CREATE VIEW item_progress_view AS
SELECT
    i.id AS item_id,
    i.status,
    COALESCE(df.name, '') AS flow_name,
    COALESCE(dr.id, '') AS run_id,
    COALESCE(dr.current_stage, '') AS current_stage,
    COALESCE(df.target_env, '') AS target_env,
    '' AS stage_progress,
    '' AS done_description,
    '' AS qa_summary,
    '' AS pipeline_blocked_reason
FROM items i
LEFT JOIN deployment_flows df ON i.deployment_flow = df.id
LEFT JOIN deployment_run_items dri ON dri.item_id = i.id
LEFT JOIN deployment_runs dr ON dr.id = dri.run_id AND dr.status = 'executing';
"""


def _apply_item_query_schema() -> None:
    """``init_test_db`` apply_schema strategy: the extended item-query schema +
    seed rows against the repointed per-test Postgres authority. Seeding lives
    here (not a post-yield step) so the subprocess under test, which inherits
    the repointed DSN, reads the same per-test database."""
    apply_inline_ddl(_ITEM_QUERY_SCHEMA)
    conn = db_backend.connect()

    ts = "2026-03-01T00:00:00Z"

    # Item 1: implementing, yoke, with spec and large technical_plan
    conn.execute(
        """INSERT INTO projects
           (id, slug, name, github_repo, public_item_prefix, created_at)
           VALUES (1, 'yoke', 'Yoke', 'org/yoke', 'YOK', %s),
                  (2, 'buzz', 'Buzz', 'org/buzz', 'BUZ', %s)""",
        (ts, ts),
    )
    conn.execute(
        """INSERT INTO items
           (id, title, type, status, priority, project_id, project_sequence,
            created_at, updated_at, source, frozen, spec, technical_plan)
           VALUES (1, 'Implementing item', 'issue', 'implementing', 'high', 1, 1,
                   %s, %s, 'user', 0, 'Spec content here', %s)""",
        (ts, ts, _LARGE_SPEC_TEXT),
    )

    # Item 2: idea, yoke
    conn.execute(
        """INSERT INTO items
           (id, title, type, status, priority, project_id, project_sequence,
            created_at, updated_at, source, frozen)
           VALUES (2, 'Idea item', 'issue', 'idea', 'medium', 1, 2,
                   %s, %s, 'user', 0)""",
        (ts, ts),
    )

    # Item 3: idea, buzz project
    conn.execute(
        """INSERT INTO items
           (id, title, type, status, priority, project_id, project_sequence,
            created_at, updated_at, source, frozen)
           VALUES (3, 'Buzz idea', 'issue', 'idea', 'low', 2, 3,
                   %s, %s, 'user', 0)""",
        (ts, ts),
    )

    # Item 4: done, yoke
    conn.execute(
        """INSERT INTO items
           (id, title, type, status, priority, project_id, project_sequence,
            created_at, updated_at, source, frozen)
           VALUES (4, 'Done item', 'epic', 'done', 'medium', 1, 4,
                   %s, %s, 'user', 0)""",
        (ts, ts),
    )

    # Item 5: frozen
    conn.execute(
        """INSERT INTO items
           (id, title, type, status, priority, project_id, project_sequence,
            created_at, updated_at, source, frozen)
           VALUES (5, 'Frozen item', 'issue', 'planned', 'medium', 1, 5,
                   %s, %s, 'user', 1)""",
        (ts, ts),
    )

    # Deployment flow for progress view test
    flow_stages = json.dumps([
        {"name": "merged", "executor": "auto"},
        {"name": "prod-deploy", "executor": "github-actions-workflow"},
    ])
    conn.execute(
        """INSERT INTO deployment_flows
           (id, project_id, name, stages, target_env, created_at)
           VALUES ('test-flow', 1, 'TestFlow', %s, 'production', %s)""",
        (flow_stages, ts),
    )

    # Item 6: release with active deployment run (for progress view)
    conn.execute(
        """INSERT INTO items
           (id, title, type, status, priority, project_id, project_sequence,
            created_at, updated_at, source, frozen,
            deploy_stage, deployment_flow)
           VALUES (6, 'Deploying item', 'issue', 'release', 'high', 1, 6,
                   %s, %s, 'user', 0,
                   'prod-deploy', 'test-flow')""",
        (ts, ts),
    )

    conn.execute(
        """INSERT INTO deployment_runs
           (id, project_id, flow, status, current_stage, created_at)
           VALUES ('run-001', 1, 'test-flow', 'executing', 'prod-deploy', %s)""",
        (ts,),
    )
    conn.execute(
        """INSERT INTO deployment_run_items (run_id, item_id, added_at)
           VALUES ('run-001', 6, %s)""",
        (ts,),
    )

    conn.commit()
    conn.close()


@pytest.fixture()
def item_query_env():
    """Create a test database with extended schema for item query testing.

    ``YOKE_PG_DSN`` is repointed to a disposable Postgres database for the
    fixture's lifetime, then restored and the database is dropped. The
    service_client subprocess inherits the repointed env via ``os.environ.copy()``
    so it reads the same per-test DB this fixture seeds.
    """
    import shutil

    tmp_dir = tempfile.mkdtemp(prefix="yoke-item-query-")
    with init_test_db(Path(tmp_dir), apply_schema=_apply_item_query_schema) as db_path:
        yield {"db_path": db_path, "tmp_dir": tmp_dir}
    shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# parity_env — render-parity fixture (test_parity_render, test_parity_render_board)
# ---------------------------------------------------------------------------
#
# The render parity modules compare the FastAPI API surface against the
# service_client.py subprocess over one shared dataset. Both surfaces resolve
# their connection through the backend factory, so a single per-test database —
# a disposable Postgres database — backs BOTH: the API dependency overrides read
# it, and the subprocess inherits the same repointed DSN. There is no separate
# seeded database and no startup-gate decoy; parity is measured against one
# authority.
#
# The builder is ``make_read_parity_env``, shared with the
# test_parity_service_client_* cluster; it applies the strict project-identity
# parity fixture from ``parity_service_client_project_fixture``.


@pytest.fixture()
def parity_env():
    """Postgres-backed render-parity environment.

    Yields ``{"db_path", "tmp_dir", "client"}`` from :func:`make_read_parity_env`
    so the in-process FastAPI ``TestClient`` and the service_client subprocess
    read the same disposable per-test Postgres database.
    """
    from runtime.api.parity_service_client_test_helpers import (
        make_read_parity_env,
    )

    with make_read_parity_env() as env:
        yield env
