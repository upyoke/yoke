"""Packaged-template rendered artifact bundle for a neutral external project."""

from __future__ import annotations

import json
from pathlib import Path

from runtime.api.fixtures import pg_testdb
from yoke_core.domain import project_artifact_bundle, yaml_helper
from yoke_core.domain.project_renderer_values import (
    CONFIGURE_AWS_CREDENTIALS_ACTION,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
EXTERNAL_PROJECT = "sample-service"
EXACT_DISTRIBUTION_ID = "EEXAMPLE123"


def _external_project_db():
    db_name = pg_testdb.create_test_database()
    conn = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(db_name),
        db_name,
    )
    conn.execute(
        "CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT UNIQUE, "
        "name TEXT, public_item_prefix TEXT DEFAULT 'SMP')"
    )
    conn.execute(
        "CREATE TABLE sites (id TEXT PRIMARY KEY, project_id INTEGER, "
        "name TEXT, settings TEXT)"
    )
    conn.execute(
        "CREATE TABLE environments (id TEXT PRIMARY KEY, site TEXT, "
        "name TEXT, settings TEXT)"
    )
    conn.execute(
        "CREATE TABLE project_capabilities (project_id INTEGER, type TEXT, "
        "settings TEXT)"
    )
    conn.execute(
        "CREATE TABLE project_github_repo_bindings (project_id INTEGER PRIMARY "
        "KEY, github_repo TEXT, api_url TEXT, status TEXT, last_verified_at TEXT)"
    )
    conn.execute(
        "INSERT INTO projects (id, slug, name) VALUES (%s, %s, %s)",
        (71, EXTERNAL_PROJECT, "Sample Service"),
    )
    conn.execute(
        "INSERT INTO project_github_repo_bindings "
        "(project_id, github_repo, api_url, status, last_verified_at) "
        "VALUES (%s, %s, %s, %s, %s)",
        (
            71,
            "example/sample-service",
            "https://api.github.com",
            "active",
            "2026-07-18T12:00:00Z",
        ),
    )
    conn.execute(
        "INSERT INTO sites (id, project_id, name, settings) VALUES (%s, %s, %s, %s)",
        (
            "sample-web",
            71,
            "Sample Web",
            json.dumps(
                {
                    "domains": [{"domain_name": "sample.example.test"}],
                    "cdn": [{"distribution_id": EXACT_DISTRIBUTION_ID}],
                }
            ),
        ),
    )
    conn.execute(
        "INSERT INTO environments (id, site, name, settings) VALUES (%s, %s, %s, %s)",
        (
            "sample-production",
            "sample-web",
            "production",
            json.dumps(
                {
                    "renderer_primary": True,
                    "hosts": {"origin": "origin.sample.example.test"},
                    "servers": [
                        {
                            "host": "203.0.113.72",
                            "description": "External production VPS",
                        }
                    ],
                }
            ),
        ),
    )
    capabilities = {
        "aws-admin": {"region": "us-east-1", "account_id": "123456789012"},
        "ssh": {"default_user": "deploy"},
        "webapp-runtime": {"web_port": 3000, "api_port": 8000},
        "health-endpoint": {"health_path": "/", "smoke_paths": ["/login"]},
        "pulumi-state": {
            "deploy_namespace": EXTERNAL_PROJECT,
            "state_bucket": "sample-pulumi-state",
            "kms_key_alias": "alias/sample-pulumi-state",
            "stacks": ["infra", "vps"],
        },
    }
    for cap_type, settings in capabilities.items():
        conn.execute(
            "INSERT INTO project_capabilities (project_id, type, settings) "
            "VALUES (%s, %s, %s)",
            (71, cap_type, json.dumps(settings)),
        )
    return conn


def test_packaged_source_renders_parsed_oidc_workflows_for_external_project() -> None:
    source = REPO_ROOT / "templates/webapp/ops/deploy.yml"
    packaged = REPO_ROOT / (
        "packages/yoke-core/src/yoke_core/install_bundle_tree/"
        "templates/webapp/ops/deploy.yml"
    )
    assert source.read_bytes() == packaged.read_bytes()

    conn = _external_project_db()
    try:
        bundle = project_artifact_bundle.build_project_artifact_bundle(
            conn, EXTERNAL_PROJECT
        )
    finally:
        conn.close()

    assert bundle["project_slug"] == EXTERNAL_PROJECT
    assert bundle["template_source"] == "packaged-template-mirror"
    assert len(bundle["template_digest"]) == 64
    assert len(bundle["settings_digest"]) == 64
    assert len(bundle["content_digest"]) == 64
    assert bundle["checkout_identity"] == {
        "project_id": 71,
        "project_slug": EXTERNAL_PROJECT,
        "github_repo": "example/sample-service",
        "github_web_url": "https://github.com",
    }
    artifacts = {entry["path"]: entry for entry in bundle["artifacts"]}
    deploy = artifacts[f".github/workflows/{EXTERNAL_PROJECT}-deploy.yml"]["content"]
    parsed = yaml_helper.parse_document(deploy)

    assert parsed["permissions"] == {"contents": "read", "id-token": "write"}
    configure = next(
        step
        for step in parsed["jobs"]["deploy"]["steps"]
        if step.get("name") == "Configure AWS delivery credentials"
    )
    assert configure["uses"] == CONFIGURE_AWS_CREDENTIALS_ACTION.split(" #", 1)[0]
    assert configure["with"]["role-to-assume"] == (
        "${{ vars.YOKE_DELIVERY_CI_ROLE_ARN }}"
    )
    assert EXACT_DISTRIBUTION_ID in deploy
    assert "secrets.AWS_ACCESS_KEY_ID" not in deploy
    assert "secrets.AWS_SECRET_ACCESS_KEY" not in deploy
    assert "{{configure_aws_credentials_action}}" not in deploy
    assert "{{cloudfront_id}}" not in deploy
    assert "infra/webapp_distribution_stack.py" in artifacts
    assert "docs/yoke-generated/deployment-reference/deploy.md" in artifacts
    assert not any(path.startswith(".yoke/runbooks/") for path in artifacts)
    assert not any(
        path.startswith("infra/Pulumi.") and path != "infra/Pulumi.yaml"
        for path in artifacts
    )
    assert bundle["pulumi_stack_config"]["included"] is False


def test_source_dev_admin_override_requires_declared_server_tree(
    monkeypatch,
) -> None:
    conn = _external_project_db()
    monkeypatch.delenv("YOKE_SERVER_TREE_ROOT", raising=False)
    try:
        try:
            project_artifact_bundle.build_project_artifact_bundle(
                conn, EXTERNAL_PROJECT, source_dev_admin=True
            )
        except project_artifact_bundle.ProjectArtifactBundleError as exc:
            assert "source-dev/admin" in str(exc)
        else:
            raise AssertionError("source-dev override must fail closed")
    finally:
        conn.close()


def test_local_project_without_github_binding_still_renders() -> None:
    conn = _external_project_db()
    conn.execute(
        "DELETE FROM project_github_repo_bindings WHERE project_id=%s",
        (71,),
    )
    try:
        bundle = project_artifact_bundle.build_project_artifact_bundle(
            conn,
            EXTERNAL_PROJECT,
        )
    finally:
        conn.close()

    assert bundle["checkout_identity"] == {
        "project_id": 71,
        "project_slug": EXTERNAL_PROJECT,
        "github_repo": None,
        "github_web_url": None,
    }
