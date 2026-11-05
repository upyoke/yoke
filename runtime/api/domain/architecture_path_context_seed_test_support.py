# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from pathlib import Path

from typing import Any

import pytest

from yoke_core.domain import path_context

from yoke_core.domain.architecture_path_context_seed import (
    seed_architecture_path_context,
)

from yoke_core.domain.db_helpers import iso8601_now

from runtime.api.path_context_test_helpers import (
    emit_event,
    init_minimal_schema,
    mint_target,
)


def _write_model(conn: Any, payload: dict, project_id: int = 1) -> None:
    conn.execute(
        "DELETE FROM project_structure WHERE family = 'architecture_model'",
    )
    conn.execute(
        "INSERT INTO project_structure "
        "(project_id, family, attachment_kind, attachment_value, "
        "entry_key, payload, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (
            project_id,
            "architecture_model",
            "",
            "project",
            "",
            json.dumps(payload),
            iso8601_now(),
            iso8601_now(),
        ),
    )
    conn.commit()


def _model() -> dict:
    return {
        "layers": [
            {"id": "storage", "may_depend_on": [], "forbidden_edges": []},
            {
                "id": "service",
                "may_depend_on": ["storage"],
                "forbidden_edges": [],
            },
        ],
        "domains": [
            {
                "id": "billing",
                "path_roots": [
                    {"glob": "src/billing/schema_*.py", "layer": "storage"},
                    {"glob": "src/billing/**", "layer": "service"},
                ],
            },
        ],
        "exemptions": [
            {"glob": "tests/**", "family": "architecture_test_surface"},
        ],
    }


def _snapshot_with(conn: Any, paths: list[str], project_id: int = 1):
    cur = conn.execute(
        "INSERT INTO path_snapshots (project_id, commit_sha, built_at) "
        "VALUES (%s, %s, %s) RETURNING id",
        (project_id, "abc1234", iso8601_now()),
    )
    snapshot_id = int(cur.fetchone()[0])
    targets = {}
    for path in paths:
        tid = mint_target(conn, "yoke", path)
        targets[path] = tid
        conn.execute(
            "INSERT INTO path_snapshot_entries "
            "(snapshot_id, target_id, line_count, language, module_name, "
            "area, is_generated, dependency_edges) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                snapshot_id,
                tid,
                10,
                "python",
                path.removesuffix(".py").replace("/", "."),
                None,
                0,
                "[]",
            ),
        )
    conn.commit()
    return targets


@pytest.fixture
def conn(tmp_path: Path) -> Any:
    c = init_minimal_schema(str(tmp_path / "t.db"))
    yield c
    c.close()
