"""Shared harness for the ephemeral-deploy tests.

Project-owned Pack source setup, the policy and environment the deploy
reads, and the seams that stand in for everything the deploy would
otherwise reach — so the tests assert command plans and tracking rather
than infrastructure.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil


from yoke_core.domain.deploy_environment_settings import DeployEnvironment
from yoke_core.domain.deploy_remote import CommandResult
from yoke_core.domain.ephemeral_substrate import EphemeralPolicy
from runtime.api.domain.test_deploy_remote import FakeRunner


def install_ephemeral_project_source(tmp_path: Path) -> Path:
    repository_root = Path(__file__).resolve().parents[3]
    project_root = tmp_path / "ephemeral-project"
    for pack_slug in ("ephemeral-environments", "branch-preview-hosting"):
        pack_root = repository_root / "packs" / pack_slug
        descriptor = json.loads((pack_root / "pack.json").read_text(encoding="utf-8"))
        version = descriptor["versions"][descriptor["latest_version"]]
        source_root = pack_root / version["source"]
        for record in version["files"]:
            source = source_root / record["source"]
            target = project_root / record["target"].replace("{{project_name}}", "yoke")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    core_template = repository_root / (
        "ops/core-service/docker-compose.ephemeral.yml.tmpl"
    )
    core_target = project_root / ("ops/core-service/docker-compose.ephemeral.yml.tmpl")
    core_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(core_template, core_target)
    return project_root


def policy(**overrides):
    values = dict(
        project="yoke",
        host_project="platform",
        preview_namespace="yoke-preview",
        trigger="flow",
        flow_id="yoke-branch-preview",
        preview_domain="preview.example.com",
        host_env="stage",
        api_base_port=9000,
        web_base_port=4000,
        port_range=100,
        ttl_hours=24,
    )
    values.update(overrides)
    return EphemeralPolicy(**values)


def env(**overrides) -> DeployEnvironment:
    values = dict(
        project="platform",
        deploy_namespace="platform",
        env_name="stage",
        site_id="yoke-api",
        api_host="api.stage.example.com",
        origin_host="origin.stage.example.com",
        origin_port=80,
        ssh_user="ubuntu",
        ssh_key_path="/keys/origin-example.pem",
        aws_region="us-east-1",
        aws_account_id="123456789012",
        repository_name="yoke-core",
        api_port=8765,
        health_path="/v1/health",
        stack_name="yoke-stage",
        activation_state="active",
        state_backend="s3://yoke-pulumi-state?region=us-east-1",
        database_name="yoke_stage",
    )
    values.update(overrides)
    return DeployEnvironment(**values)


SHA = "1234567890abcdef1234567890abcdef12345678"
SLUG = "ephemeral-substrate-preview"
PORT = 9067  # derive_port golden vector for the slug above


class Tracker:
    def __init__(self):
        self.calls = []

    def __call__(self, project, branch, updates, item_label=""):
        self.calls.append((project, branch, dict(updates), item_label))


def scripted_runner():
    """Results in step_runner call order (branch sha + remote convergence)."""
    return FakeRunner(
        [
            CommandResult(0, SHA + "\n", ""),  # git rev-parse branch
            CommandResult(0, "", ""),  # tls cert probe (present)
            CommandResult(0, "", ""),  # njs package probe (present)
            CommandResult(0, "", ""),  # njs dir mkdir
            CommandResult(0, "", ""),  # njs script push
            CommandResult(0, "", ""),  # nginx site push
            CommandResult(0, "", ""),  # nginx activate
            CommandResult(0, "", ""),  # cleanup script push
            CommandResult(0, "", ""),  # cleanup cron push
            CommandResult(0, "cafe01\n", ""),  # existing db-password read
            CommandResult(0, "", ""),  # slug dir prepare
            CommandResult(0, "", ""),  # compose push
            CommandResult(0, "", ""),  # db-password push
            CommandResult(0, "", ""),  # .env push
            CommandResult(0, "", ""),  # dsn push
            CommandResult(0, "", ""),  # compose pull
            CommandResult(0, "bootstrap complete", ""),  # in-container bootstrap
            CommandResult(0, "", ""),  # compose up
            CommandResult(0, "x-request-id: RID", ""),  # slug health (patched id)
        ]
    )

__all__ = [
    "PORT",
    "Tracker",
    "env",
    "SHA",
    "SLUG",
    "install_ephemeral_project_source",
    "policy",
    "scripted_runner",
]
