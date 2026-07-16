"""Canonical built-in deployment flow seed rows."""

from __future__ import annotations

import json

from yoke_contracts.github_workflow_dispatch import (
    WORKFLOW_DISPATCH_CORRELATION_INPUT,
)
from yoke_core.domain.deployment_flow_state import (
    FLOW_STATUS_ACTIVE,
    FLOW_STATUS_DISABLED,
)


def _github_workflow_stage(
    name: str, workflow: str, *, correlated: bool = False, **config,
):
    stage = {
        "name": name,
        "executor": "github-actions-workflow",
        "workflow": workflow,
        **config,
    }
    if correlated:
        stage["dispatch_correlation_input"] = (
            WORKFLOW_DISPATCH_CORRELATION_INPUT
        )
    return stage


def _hosted_release_stages(
    *,
    workflow: str,
    target_environment: str,
    release_mode: str,
    product_bridge: bool,
) -> str:
    inputs = {
        "target_environment": target_environment,
        "release_mode": release_mode,
    }
    if product_bridge:
        inputs["product_sha"] = "{head_sha}"
    else:
        inputs["platform_ref"] = "{head_sha}"
    return json.dumps([
        {"name": "merged", "executor": "auto"},
        _github_workflow_stage(
            "hosted-release",
            workflow,
            correlated=True,
            ref="main",
            inputs=inputs,
            reconcile_by_head_sha=False,
        ),
        {"name": "complete", "executor": "auto"},
    ])


SEED_FLOWS = [
    {
        "id": "yoke-internal", "project": "yoke", "name": "Internal",
        "description": "Script/doc changes, no deployment needed",
        "stages": json.dumps([
            {"kind": "migration_apply", "model_name": "primary",
             "lifecycle_phase": "implementing"},
            {"name": "merged", "executor": "auto"},
            {"name": "complete", "executor": "auto"},
        ]),
        "on_failure": "halt", "target_env": None,
        "status": FLOW_STATUS_ACTIVE,
        "done_description": "Merged to main",
    },
    {
        "id": "yoke-prod-release", "project": "yoke", "name": "Prod Release",
        "description": "Deploy Yoke core and public installer distribution to prod",
        "stages": json.dumps([
            {"kind": "migration_apply", "model_name": "primary",
             "lifecycle_phase": "implementing"},
            {"name": "merged", "executor": "auto"},
            {"name": "env-activate", "executor": "environment-activate"},
            {"name": "core-deploy", "executor": "core-container-deploy"},
            {"name": "health-check", "executor": "health-check"},
            _github_workflow_stage(
                "distribution-publish", "yoke-distribution-publish.yml",
                correlated=True,
                ref="main", inputs={"channel": "stable", "target_env": "prod",
                                    "source_sha": "{head_sha}"},
                reconcile_by_head_sha=False, qa_kind="distribution_publish",
            ),
            {"name": "complete", "executor": "auto"},
        ]),
        "on_failure": "halt", "target_env": "prod",
        "status": FLOW_STATUS_DISABLED,
        "done_description": "Yoke core deployed to prod, health check passed, and installer distribution published",
    },
    {
        "id": "yoke-stage-release", "project": "yoke", "name": "Stage Release",
        "description": "Deploy Yoke core and public installer distribution to stage (stage data is throwaway; no governed migration stage)",
        "stages": json.dumps([
            {"name": "merged", "executor": "auto"},
            {"name": "env-activate", "executor": "environment-activate"},
            {"name": "core-deploy", "executor": "core-container-deploy"},
            {"name": "health-check", "executor": "health-check"},
            _github_workflow_stage(
                "distribution-publish", "yoke-distribution-publish.yml",
                correlated=True,
                ref="stage", inputs={"channel": "latest", "target_env": "stage",
                                     "source_sha": "{head_sha}"},
                reconcile_by_head_sha=False, qa_kind="distribution_publish",
            ),
            {"name": "complete", "executor": "auto"},
        ]),
        "on_failure": "halt", "target_env": "stage",
        "status": FLOW_STATUS_DISABLED,
        "done_description": "Yoke core deployed to stage, health check passed, and stage installer distribution published",
    },
    {
        "id": "yoke-hosted-production",
        "project": "yoke",
        "name": "Production",
        "description": (
            "Release an annotated Yoke version through the Platform production train"
        ),
        "stages": _hosted_release_stages(
            workflow="platform-release-bridge.yml",
            target_environment="production",
            release_mode="normal",
            product_bridge=True,
        ),
        "on_failure": "halt",
        "target_env": "production",
        "status": FLOW_STATUS_ACTIVE,
        "done_description": "Yoke release completed through the hosted production train",
    },
    {
        "id": "yoke-hosted-production-hotfix",
        "project": "yoke",
        "name": "Production Hotfix",
        "description": (
            "Release an annotated Yoke hotfix through the Platform production train"
        ),
        "stages": _hosted_release_stages(
            workflow="platform-release-bridge.yml",
            target_environment="production",
            release_mode="hotfix",
            product_bridge=True,
        ),
        "on_failure": "halt",
        "target_env": "production",
        "status": FLOW_STATUS_ACTIVE,
        "done_description": "Yoke hotfix completed through the hosted production train",
    },
    {
        "id": "yoke-hosted-stage",
        "project": "yoke",
        "name": "Stage",
        "description": "Release an annotated Yoke version through the Platform stage train",
        "stages": _hosted_release_stages(
            workflow="platform-release-bridge.yml",
            target_environment="stage",
            release_mode="normal",
            product_bridge=True,
        ),
        "on_failure": "halt",
        "target_env": "stage",
        "status": FLOW_STATUS_ACTIVE,
        "done_description": "Yoke release completed through the hosted stage train",
    },
    {
        "id": "yoke-ephemeral-deploy", "project": "yoke", "name": "Ephemeral Deploy",
        "description": "Deploy a branch/SHA Yoke core preview environment through the shared ephemeral substrate (unmerged worktree branches; no merged gate)",
        "stages": json.dumps([
            {"name": "ephemeral-deploy", "executor": "ephemeral-deploy"},
            {"name": "complete", "executor": "auto"},
        ]),
        "on_failure": "halt", "target_env": "ephemeral",
        "status": FLOW_STATUS_ACTIVE,
        "done_description": "Yoke core preview environment deployed",
    },
    {
        "id": "platform-production",
        "project": "platform",
        "name": "Production",
        "description": "Release Platform main through the hosted production train",
        "stages": _hosted_release_stages(
            workflow="platform-release.yml",
            target_environment="production",
            release_mode="normal",
            product_bridge=False,
        ),
        "on_failure": "halt",
        "target_env": "production",
        "status": FLOW_STATUS_ACTIVE,
        "done_description": "Platform release completed through the hosted production train",
    },
    {
        "id": "platform-production-hotfix",
        "project": "platform",
        "name": "Production Hotfix",
        "description": "Release a Platform hotfix through the hosted production train",
        "stages": _hosted_release_stages(
            workflow="platform-release.yml",
            target_environment="production",
            release_mode="hotfix",
            product_bridge=False,
        ),
        "on_failure": "halt",
        "target_env": "production",
        "status": FLOW_STATUS_ACTIVE,
        "done_description": "Platform hotfix completed through the hosted production train",
    },
    {
        "id": "platform-stage",
        "project": "platform",
        "name": "Stage",
        "description": "Release Platform main through the hosted stage train",
        "stages": _hosted_release_stages(
            workflow="platform-release.yml",
            target_environment="stage",
            release_mode="normal",
            product_bridge=False,
        ),
        "on_failure": "halt",
        "target_env": "stage",
        "status": FLOW_STATUS_ACTIVE,
        "done_description": "Platform release completed through the hosted stage train",
    },
    {
        "id": "buzz-prod-release", "project": "buzz", "name": "Prod Release",
        "description": "Push-to-main triggers prod deploy via GitHub Actions with environment protection gate, then smoke test",
        "stages": json.dumps([
            {"kind": "migration_apply", "model_name": "primary",
             "lifecycle_phase": "implementing"},
            {"name": "merged", "executor": "auto"},
            _github_workflow_stage("prod-deploy", "buzz-deploy.yml"),
            _github_workflow_stage("smoke", "buzz-smoke.yml"),
            {"name": "complete", "executor": "auto"},
        ]),
        "on_failure": "halt", "target_env": "production",
        "status": FLOW_STATUS_ACTIVE,
        "done_description": "Deployed to production and smoke checks passed",
    },
    {
        "id": "buzz-prod-hotfix", "project": "buzz", "name": "Prod Hotfix",
        "description": "Manual dispatch of hotfix workflow for direct-to-prod deploy",
        "stages": json.dumps([
            {"kind": "migration_apply", "model_name": "primary",
             "lifecycle_phase": "implementing"},
            {"name": "merged", "executor": "auto"},
            _github_workflow_stage(
                "production-deploy", "buzz-hotfix.yml",
                watch_for="completed", on_failure="halt",
            ),
        ]),
        "on_failure": "halt", "target_env": "production",
        "status": FLOW_STATUS_ACTIVE,
        "done_description": "Hotfix deployed to production",
    },
    {
        "id": "buzz-internal", "project": "buzz", "name": "Internal",
        "description": "Doc or config change, no deployment",
        "stages": json.dumps([
            {"name": "merged", "executor": "auto"},
            {"name": "complete", "executor": "auto"},
        ]),
        "on_failure": "halt", "target_env": None,
        "status": FLOW_STATUS_ACTIVE,
        "done_description": "Merged to main",
    },
]


__all__ = ["SEED_FLOWS"]
