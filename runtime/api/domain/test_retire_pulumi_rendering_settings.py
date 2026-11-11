"""Migration 0108 strips renderer-only settings from live projects only."""

import json
from pathlib import Path
import sqlite3

import pytest

from yoke_core.domain.migration_history import load_migration_module

_SITE = {
    "deploy_namespace": "acme",
    "cdn": {"origin_id": "o", "distribution_bucket_name": "b", "distribution_id": "E1"},
    "domains": [{
        "domain_name": "acme.test", "dns_provider": "route53",
        "hosted_zone_id": "Z1", "manage_registration": True,
        "txt_records": [{"id": "t"}], "mx_records": [], "certificate_arn": "arn",
    }],
    "pulumi": {"stacks": ["infra"], "stack_state": {"acme-infra": {}}},
}
_ENVIRONMENT = {
    "database": {
        "name": "acme_prod", "location": "box", "master_username": "admin",
        "engine_version": "16", "min_capacity_acu": 0, "max_capacity_acu": 2,
        "backup_retention_days": 7, "allowed_security_group_ids": [],
        "seconds_until_auto_pause": 1800,
    },
    "distribution": {"bucket_name": "b", "repository_variable_namespace": "ACME"},
    "pulumi": {
        "stack_name": "acme-prod", "origin_vps_stack_name": "acme-vps",
        "encrypted_key": "k", "secrets_provider": "awskms://alias/a",
    },
    "servers": [{
        "host": "203.0.113.9", "ssh_key_path": "~/.ssh/acme",
        "instance_type": "t4g.small", "root_volume_gb": 40,
        "aws_key_pair_name": "acme", "iam_instance_profile_name": "p",
        "description": "origin",
    }],
}
_CAPABILITIES = {
    "pulumi-state": {
        "state_bucket": "acme-state", "kms_key_alias": "alias/acme",
        "stacks": ["infra"], "infra_stack_name": "acme-infra",
        "vps_stack_name": "acme-vps", "stack_state": {"acme-infra": {}},
        "migration_receipts": {}, "component_type_aliases": {"infra": ["x"]},
    },
    "container-registry": {
        "repository": "acme-core", "manage_platform_image_lifecycle": True,
    },
    "github": {"repo_owner": "acme", "repo_name": "web", "ci_oidc_manage_provider": True},
    "aws-route53": {"hosted_zone_id": "Z1"},
}


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
    conn.execute("INSERT INTO projects VALUES (1, NULL), (2, '2026-11-01')")
    row = 0
    for project in (1, 2):
        for cap_type, settings in _CAPABILITIES.items():
            row += 1
            conn.execute(
                "INSERT INTO project_capabilities VALUES "
                f"({row}, {project}, '{cap_type}', '{json.dumps(settings)}')"
            )
        conn.execute(f"INSERT INTO sites VALUES ({project}, {project}, '{json.dumps(_SITE)}')")
        conn.execute(
            f"INSERT INTO environments VALUES ({project}, {project}, "
            f"'{json.dumps(_ENVIRONMENT)}')"
        )
    for template in ("aws-route53", "github", "container-registry"):
        conn.execute(f"INSERT INTO capability_templates VALUES ('{template}', '[]')")


def _settings(conn, table: str, where: str) -> dict:
    return json.loads(conn.execute(f"SELECT settings FROM {table} WHERE {where}").fetchone()[0])


@pytest.mark.parametrize("backend", ["postgres", "sqlite"])
def test_strips_renderer_settings_keeps_runtime_ones_and_skips_retired(test_db, backend):
    conn = test_db if backend == "postgres" else sqlite3.connect(":memory:")
    _seed(conn)
    from yoke_core.domain import migrations

    path = Path(migrations.__file__).parent / "0108_retire_pulumi_rendering_settings.py"
    module = load_migration_module(path, path.stem)
    module.apply(conn)
    module.apply(conn)

    assert _settings(conn, "sites", "id=1") == {
        "deploy_namespace": "acme",
        "cdn": {"distribution_id": "E1"},
        "domains": [{"domain_name": "acme.test", "dns_provider": "route53"}],
    }
    assert _settings(conn, "environments", "id=1") == {
        "database": {"name": "acme_prod", "location": "box"},
        "distribution": {"bucket_name": "b"},
        "pulumi": {"stack_name": "acme-prod", "origin_vps_stack_name": "acme-vps"},
        "servers": [{"host": "203.0.113.9", "ssh_key_path": "~/.ssh/acme"}],
    }
    caps = {
        row[0]: json.loads(row[1])
        for row in conn.execute(
            "SELECT type, settings FROM project_capabilities WHERE project_id=1"
        ).fetchall()
    }
    assert caps == {
        "pulumi-state": {
            "state_bucket": "acme-state", "kms_key_alias": "alias/acme",
            "component_type_aliases": {"infra": ["x"]},
        },
        "container-registry": {"repository": "acme-core"},
        "github": {"repo_owner": "acme", "repo_name": "web"},
    }
    templates = dict(
        conn.execute("SELECT id, required_config FROM capability_templates").fetchall()
    )
    assert "aws-route53" not in templates
    assert "manage_platform_image_lifecycle" not in templates["container-registry"]
    assert "ci_oidc_manage_provider" not in templates["github"]
    assert _settings(conn, "sites", "id=2") == _SITE
    assert _settings(conn, "environments", "id=2") == _ENVIRONMENT
    retired_types = {
        row[0] for row in conn.execute(
            "SELECT type FROM project_capabilities WHERE project_id=2"
        ).fetchall()
    }
    assert retired_types == set(_CAPABILITIES)
