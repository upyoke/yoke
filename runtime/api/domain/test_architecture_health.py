"""The shared architecture-health computer.

One definition of coverage and violations serves the Doctor checks,
the board section, and the dashboard read surface. These tests seed a
small classified tree and assert the aggregate: coverage counts,
violation counts, examples, and the declared-map summary.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from yoke_core.domain import path_context
from yoke_core.domain.architecture_health import (
    compute_architecture_health,
)
from yoke_core.domain.db_helpers import iso8601_now
from runtime.api.path_context_test_helpers import (
    emit_event,
    init_minimal_schema,
    mint_target,
)


def _write_model(conn: Any, payload: dict, project_id: int = 1) -> None:
    conn.execute(
        "INSERT INTO project_structure "
        "(project_id, family, attachment_kind, attachment_value, "
        "entry_key, payload, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (project_id, "architecture_model", "", "project", "",
         json.dumps(payload), iso8601_now(), iso8601_now()),
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
                "path_roots": [{"glob": "src/**", "layer": "service"}],
            },
        ],
        "cross_cutting_entrypoints": {
            "storage_access": {
                "approved_modules": ["src.gateway"],
                "guarded_imports": ["sqlite3.connect"],
            },
        },
    }


@pytest.fixture
def conn(tmp_path: Path) -> Any:
    c = init_minimal_schema(str(tmp_path / "t.db"))
    yield c
    c.close()


def _entry(conn, snapshot_id: int, tid: int, module: str, edges) -> None:
    conn.execute(
        "INSERT INTO path_snapshot_entries "
        "(snapshot_id, target_id, line_count, language, module_name, "
        "area, is_generated, dependency_edges) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (snapshot_id, tid, 10, "python", module, None, 0,
         json.dumps(edges)),
    )


def test_undeclared_map_reports_undeclared(conn) -> None:
    assert compute_architecture_health(conn, 1) == {"declared": False}


def test_aggregate_counts_coverage_and_violations(conn) -> None:
    _write_model(conn, _model())
    cur = conn.execute(
        "INSERT INTO path_snapshots (project_id, commit_sha, built_at) "
        "VALUES (%s, %s, %s) RETURNING id",
        (1, "abc1234", iso8601_now()),
    )
    snap = int(cur.fetchone()[0])

    classified = mint_target(conn, "yoke", "src/api.py")
    storage = mint_target(conn, "yoke", "src/store.py")
    exempt = mint_target(conn, "yoke", "fixtures/sample.py")
    floater = mint_target(conn, "yoke", "scripts/loose.py")
    event_id = emit_event(conn, name="ContextAssigned")
    path_context.put_context_value(
        conn, target_id=classified,
        context_family=path_context.FAMILY_ARCHITECTURE_LAYER,
        entry_key="", value={"layer": "storage"},
        recorded_event_id=event_id,
    )
    path_context.put_context_value(
        conn, target_id=storage,
        context_family=path_context.FAMILY_ARCHITECTURE_LAYER,
        entry_key="", value={"layer": "service"},
        recorded_event_id=event_id,
    )
    path_context.put_context_value(
        conn, target_id=exempt,
        context_family=path_context.FAMILY_FIXTURE,
        entry_key="", value={"reason": "fixture"},
        recorded_event_id=event_id,
    )

    # storage-layer module importing a service-layer module is a
    # direction the rules omit -> forbidden-edge violation; the same
    # file also imports the guarded symbol directly.
    _entry(conn, snap, classified, "src.api", [
        {
            "source_module": "src.api",
            "imported_module": "src.store",
            "imported_name": "store",
        },
        {
            "source_module": "src.api",
            "imported_module": "sqlite3",
            "imported_name": "connect",
        },
    ])
    _entry(conn, snap, storage, "src.store", [])
    _entry(conn, snap, exempt, "fixtures.sample", [])
    _entry(conn, snap, floater, "scripts.loose", [])
    conn.commit()

    health = compute_architecture_health(conn, 1)
    assert health["declared"] is True
    assert health["python_paths"] == 4
    assert health["classified"] == 2
    assert health["exempt"] == 1
    assert health["unclassified"] == 1
    assert health["coverage_pct"] == 75.0
    assert health["forbidden_edge_count"] == 1
    assert health["forbidden_edge_examples"][0]["path"] == "src/api.py"
    assert health["forbidden_edge_examples"][0]["imported_layer"] == "service"
    assert health["cross_cutting_count"] == 1
    assert health["cross_cutting_examples"][0]["guarded_symbol"] == (
        "sqlite3.connect"
    )
    assert health["entrypoints"] == ["storage_access"]
    assert [d["id"] for d in health["domains"]] == ["billing"]
    assert [layer["id"] for layer in health["layers"]] == [
        "storage", "service",
    ]
