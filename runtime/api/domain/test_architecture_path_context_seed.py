"""Deriving per-file classifications from the enriched map.

The seeder converges ``path_context_values`` with the declared map:
exemption patterns win over domain patterns, operator-authored rows
(no ``glob`` in the value) survive every refresh, and derived rows are
removed when their pattern no longer matches.
"""

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
            (snapshot_id, tid, 10, "python",
             path.removesuffix(".py").replace("/", "."), None, 0, "[]"),
        )
    conn.commit()
    return targets


def _direct_value(conn: Any, target_id: int, family: str):
    row = conn.execute(
        "SELECT value FROM path_context_values "
        "WHERE target_id = %s AND context_family = %s AND entry_key = ''",
        (target_id, family),
    ).fetchone()
    return json.loads(row[0]) if row else None


@pytest.fixture
def conn(tmp_path: Path) -> Any:
    c = init_minimal_schema(str(tmp_path / "t.db"))
    yield c
    c.close()


def test_no_declared_map_reports_undeclared(conn) -> None:
    result = seed_architecture_path_context(
        conn, 1, recorded_event_id=emit_event(conn, name="MapSeeded"),
    )
    assert result.declared is False


def test_patterns_derive_layer_and_domain_rows(conn) -> None:
    _write_model(conn, _model())
    targets = _snapshot_with(
        conn,
        ["src/billing/schema_tables.py", "src/billing/invoice.py"],
    )
    result = seed_architecture_path_context(
        conn, 1, recorded_event_id=emit_event(conn, name="MapSeeded"),
    )
    assert result.declared and result.layer_rows == 2
    schema_row = _direct_value(
        conn, targets["src/billing/schema_tables.py"],
        path_context.FAMILY_ARCHITECTURE_LAYER,
    )
    assert schema_row == {
        "layer": "storage", "glob": "src/billing/schema_*.py",
    }
    invoice_row = _direct_value(
        conn, targets["src/billing/invoice.py"],
        path_context.FAMILY_ARCHITECTURE_LAYER,
    )
    assert invoice_row["layer"] == "service"
    domain_row = _direct_value(
        conn, targets["src/billing/invoice.py"],
        path_context.FAMILY_ARCHITECTURE_DOMAIN,
    )
    assert domain_row["domain"] == "billing"


def test_exemption_pattern_wins_and_star_stays_in_segment(conn) -> None:
    _write_model(conn, _model())
    targets = _snapshot_with(
        conn,
        ["tests/test_invoice.py", "src/billing/deep/nested.py"],
    )
    result = seed_architecture_path_context(
        conn, 1, recorded_event_id=emit_event(conn, name="MapSeeded"),
    )
    assert result.exemption_rows == 1
    assert _direct_value(
        conn, targets["tests/test_invoice.py"],
        "architecture_test_surface",
    ) == {"glob": "tests/**"}
    # `schema_*.py` must not cross segments; deep/nested classifies via
    # the `**` catch-all instead.
    nested = _direct_value(
        conn, targets["src/billing/deep/nested.py"],
        path_context.FAMILY_ARCHITECTURE_LAYER,
    )
    assert nested["layer"] == "service"


def test_operator_rows_survive_reseeding(conn) -> None:
    _write_model(conn, _model())
    targets = _snapshot_with(conn, ["src/billing/invoice.py"])
    operator_event = emit_event(conn, name="OperatorOverride")
    path_context.put_context_value(
        conn, target_id=targets["src/billing/invoice.py"],
        context_family=path_context.FAMILY_ARCHITECTURE_LAYER,
        entry_key="", value={"layer": "storage"},
        recorded_event_id=operator_event,
    )
    result = seed_architecture_path_context(
        conn, 1, recorded_event_id=emit_event(conn, name="MapSeeded"),
    )
    assert result.operator_rows_kept >= 1
    kept = _direct_value(
        conn, targets["src/billing/invoice.py"],
        path_context.FAMILY_ARCHITECTURE_LAYER,
    )
    assert kept == {"layer": "storage"}


def test_reseeding_removes_rows_the_map_no_longer_derives(conn) -> None:
    _write_model(conn, _model())
    targets = _snapshot_with(conn, ["src/billing/invoice.py"])
    seed_architecture_path_context(
        conn, 1, recorded_event_id=emit_event(conn, name="MapSeeded"),
    )
    narrowed = _model()
    narrowed["domains"][0]["path_roots"] = [
        {"glob": "src/billing/schema_*.py", "layer": "storage"},
    ]
    _write_model(conn, narrowed)
    result = seed_architecture_path_context(
        conn, 1, recorded_event_id=emit_event(conn, name="MapReseeded"),
    )
    assert result.removed_rows == 2
    assert result.unclassified == 0  # counted only when nothing existed
    assert _direct_value(
        conn, targets["src/billing/invoice.py"],
        path_context.FAMILY_ARCHITECTURE_LAYER,
    ) is None


def test_unmatched_paths_count_as_unclassified(conn) -> None:
    _write_model(conn, _model())
    _snapshot_with(conn, ["scripts/loose.py"])
    result = seed_architecture_path_context(
        conn, 1, recorded_event_id=emit_event(conn, name="MapSeeded"),
    )
    assert result.unclassified == 1
