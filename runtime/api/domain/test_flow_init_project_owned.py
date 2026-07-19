"""Flow schema boot and repository-owned declaration coverage."""

from __future__ import annotations

import json
from pathlib import Path

from yoke_core.domain.deployment_flow_declaration_schema import (
    normalize_document,
)
from yoke_core.domain.flow_init import cmd_init as flow_cmd_init


ROOT = Path(__file__).resolve().parents[3]


def test_schema_init_does_not_seed_project_delivery_topology(
    tmp_path: Path,
) -> None:
    from runtime.api.fixtures.file_test_db import init_test_db
    from yoke_core.domain import db_backend

    def _apply() -> None:
        conn = db_backend.connect()
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS projects ("
                "id BIGINT PRIMARY KEY, slug TEXT NOT NULL UNIQUE, "
                "created_at TEXT)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS items (id BIGINT PRIMARY KEY, status TEXT)"
            )
            conn.execute("INSERT INTO projects (id, slug) VALUES (41, 'yoke')")
            conn.execute("INSERT INTO projects (id, slug) VALUES (43, 'platform')")
            conn.commit()
        finally:
            conn.close()

    with init_test_db(tmp_path, apply_schema=_apply):
        conn = db_backend.connect()
        try:
            flow_cmd_init(conn)
            count = conn.execute("SELECT COUNT(*) FROM deployment_flows").fetchone()[0]
            assert int(count) == 0
        finally:
            conn.close()


def test_yoke_checkout_owns_valid_flow_declarations() -> None:
    document = json.loads(
        (ROOT / ".yoke" / "deployment-flows.json").read_text(encoding="utf-8")
    )
    normalized = normalize_document(document)
    by_id = {flow.id: flow for flow in normalized.flows}

    assert normalized.default_flow == "yoke-internal"
    assert "yoke-branch-preview" in by_id
    assert by_id["yoke-branch-preview"].target_env == "ephemeral"
    assert json.loads(by_id["yoke-branch-preview"].stages) == [
        {"name": "ephemeral-deploy", "executor": "ephemeral-deploy"},
        {"name": "complete", "executor": "auto"},
    ]
    assert "yoke-ephemeral-deploy" not in by_id


def test_yoke_hosted_flows_keep_dispatch_correlation() -> None:
    document = json.loads(
        (ROOT / ".yoke" / "deployment-flows.json").read_text(encoding="utf-8")
    )
    normalized = normalize_document(document)
    stages = [
        stage
        for flow in normalized.flows
        for stage in json.loads(flow.stages)
        if stage.get("executor") == "github-actions-workflow"
    ]
    assert stages
    assert {stage["dispatch_correlation_input"] for stage in stages} == {
        "yoke_dispatch_id"
    }
    assert all(stage["wait_for_ci"] is False for stage in stages)
