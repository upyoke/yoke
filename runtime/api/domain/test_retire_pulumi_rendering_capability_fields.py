"""Migration 0109 makes every capability row meet the shipped settings contract."""

import json
from pathlib import Path
import sqlite3

import pytest

from yoke_core.domain.migration_history import load_migration_module
from yoke_core.tools.migration_rehearsal_release_surfaces import (
    _validate_capability_contracts,
)

_CAPABILITIES = {
    "pulumi-state": {
        "state_bucket": "acme-state", "kms_key_alias": "alias/acme",
        "stacks": ["infra"], "stack_state": {"acme-infra": {}},
        "infra_stack_name": "acme-infra", "vps_stack_name": "acme-vps",
        "migration_receipts": {}, "component_type_aliases": {"infra": ["x"]},
    },
    "container-registry": {
        "repository": "acme-core", "manage_platform_image_lifecycle": True,
    },
    "github": {"repo_owner": "acme", "repo_name": "web", "ci_oidc_manage_provider": True},
    "aws-route53": {"hosted_zone_id": "Z1"},
}


def _migration(name: str):
    from yoke_core.domain import migrations

    path = Path(migrations.__file__).parent / f"{name}.py"
    return load_migration_module(path, path.stem)


def _seed(conn) -> None:
    for statement in (
        "CREATE TEMP TABLE projects (id INTEGER, retired_at TEXT)",
        "CREATE TEMP TABLE project_capabilities (id INTEGER, project_id INTEGER, "
        "type TEXT, settings TEXT)",
        "CREATE TEMP TABLE capability_templates (id TEXT, required_config TEXT)",
        "CREATE TEMP TABLE sites (id INTEGER, project_id INTEGER, settings TEXT)",
        "CREATE TEMP TABLE environments (id INTEGER, project_id INTEGER, settings TEXT)",
    ):
        conn.execute(statement)
    # Project 2 is retired, like buzz on yoke_tenant_4.
    conn.execute("INSERT INTO projects VALUES (1, NULL), (2, '2026-10-14')")
    row = 0
    for project in (1, 2):
        for cap_type, settings in _CAPABILITIES.items():
            row += 1
            conn.execute(
                "INSERT INTO project_capabilities VALUES "
                f"({row}, {project}, '{cap_type}', '{json.dumps(settings)}')"
            )
    conn.execute(
        "INSERT INTO sites VALUES (2, 2, '{\"pulumi\": {\"stacks\": [\"infra\"]}}')"
    )
    for template in ("aws-route53", "github", "container-registry"):
        conn.execute(f"INSERT INTO capability_templates VALUES ('{template}', '[]')")


@pytest.mark.parametrize("backend", ["postgres", "sqlite"])
def test_retired_project_capabilities_meet_contract_after_0109(test_db, backend):
    conn = test_db if backend == "postgres" else sqlite3.connect(":memory:")
    _seed(conn)
    _migration("0108_retire_pulumi_rendering_settings").apply(conn)

    with pytest.raises(AssertionError, match="project 2 capability "):
        _validate_capability_contracts(conn)

    follow_on = _migration("0109_retire_pulumi_rendering_capability_fields")
    follow_on.apply(conn)
    follow_on.apply(conn)

    _validate_capability_contracts(conn)
    caps = {
        (row[0], row[1]): json.loads(row[2])
        for row in conn.execute(
            "SELECT project_id, type, settings FROM project_capabilities"
        ).fetchall()
    }
    for project in (1, 2):
        assert caps[(project, "pulumi-state")] == {
            "state_bucket": "acme-state", "kms_key_alias": "alias/acme",
            "component_type_aliases": {"infra": ["x"]},
        }
        assert caps[(project, "container-registry")] == {"repository": "acme-core"}
        assert caps[(project, "github")] == {"repo_owner": "acme", "repo_name": "web"}
        assert (project, "aws-route53") not in caps
    retired_site = conn.execute("SELECT settings FROM sites WHERE id=2").fetchone()[0]
    assert json.loads(retired_site) == {"pulumi": {"stacks": ["infra"]}}
