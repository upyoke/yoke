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
    independent_environment: bool = False,
    wait_for_ci: bool = True,
) -> str:
    if product_bridge:
        inputs = {
            "target_environment": target_environment,
            "release_mode": release_mode,
        }
        inputs["product_sha"] = "{head_sha}"
        inputs["deployment_run_id"] = "{run_id}"
        releases = [("hosted-release", inputs)]
    else:
        environments = (
            ("stage", "production")
            if (
                target_environment == "production"
                and release_mode == "normal"
                and not independent_environment
            )
            else (target_environment,)
        )
        releases = [
            (
                f"hosted-{environment}",
                {
                    "target_environment": environment,
                    "release_mode": release_mode,
                    "platform_ref": "{head_sha}",
                },
            )
            for environment in environments
        ]
    return json.dumps(
        [{"name": "merged", "executor": "auto"}]
        + [
            _github_workflow_stage(
                name,
                workflow,
                correlated=True,
                ref="main",
                inputs=inputs,
                reconcile_by_head_sha=False,
                wait_for_ci=wait_for_ci,
            )
            for name, inputs in releases
        ]
        + [{"name": "complete", "executor": "auto"}]
    )


BUZZ_PRODUCTION_RELEASE_FLOW_ID = "buzz-production-release"
BUZZ_PRODUCTION_HOTFIX_FLOW_ID = "buzz-production-hotfix"

_BUZZ_MIGRATION_STAGE = {
    "kind": "migration_apply",
    "model_name": "primary",
    "lifecycle_phase": "implementing",
}
_BUZZ_MERGED_STAGE = {"name": "merged", "executor": "auto"}
_BUZZ_COMPLETE_STAGE = {"name": "complete", "executor": "auto"}
_BUZZ_SMOKE_STAGE = _github_workflow_stage("smoke", "buzz-smoke.yml")
_BUZZ_RELEASE_STAGES = json.dumps([
    _BUZZ_MIGRATION_STAGE,
    _BUZZ_MERGED_STAGE,
    _github_workflow_stage("prod-deploy", "buzz-deploy.yml"),
    _BUZZ_SMOKE_STAGE,
    _BUZZ_COMPLETE_STAGE,
])
_BUZZ_HOTFIX_DEPLOY_STAGE = _github_workflow_stage(
    "production-deploy",
    "buzz-hotfix.yml",
    watch_for="completed",
    on_failure="halt",
)
_BUZZ_HOTFIX_PREDECESSOR_STAGES = json.dumps([
    _BUZZ_MIGRATION_STAGE,
    _BUZZ_MERGED_STAGE,
    _BUZZ_HOTFIX_DEPLOY_STAGE,
])
_BUZZ_HOTFIX_STAGES = json.dumps([
    _BUZZ_MIGRATION_STAGE,
    _BUZZ_MERGED_STAGE,
    _BUZZ_HOTFIX_DEPLOY_STAGE,
    _BUZZ_SMOKE_STAGE,
    _BUZZ_COMPLETE_STAGE,
])
_BUZZ_RELEASE_WITH_LOCAL_APPROVAL_STAGES = json.dumps([
    _BUZZ_MIGRATION_STAGE,
    _BUZZ_MERGED_STAGE,
    {
        "name": "ephemeral-verify",
        "executor": "ephemeral-verify",
        "workflow": "buzz-ephemeral.yml",
    },
    {"name": "approve-deploy", "executor": "human-approval"},
    _github_workflow_stage("prod-deploy", "buzz-deploy.yml"),
    _BUZZ_SMOKE_STAGE,
    _BUZZ_COMPLETE_STAGE,
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
        "status": FLOW_STATUS_DISABLED,
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
        "status": FLOW_STATUS_DISABLED,
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
        "status": FLOW_STATUS_DISABLED,
        "done_description": "Yoke release completed through the hosted stage train",
    },
    {
        "id": "yoke-hosted-production-hotfix-no-ci-gate",
        "project": "yoke",
        "name": "Production Hotfix (No CI Gate)",
        "description": (
            "Dispatch an annotated Yoke hotfix through the Platform "
            "production train without waiting for repository CI"
        ),
        "stages": _hosted_release_stages(
            workflow="platform-release-bridge.yml",
            target_environment="production",
            release_mode="hotfix",
            product_bridge=True,
            wait_for_ci=False,
        ),
        "on_failure": "halt",
        "target_env": "production",
        "status": FLOW_STATUS_ACTIVE,
        "done_description": "Yoke hotfix completed through the hosted production train",
    },
    {
        "id": "yoke-hosted-stage-no-ci-gate",
        "project": "yoke",
        "name": "Stage (No CI Gate)",
        "description": (
            "Dispatch an annotated Yoke version through the Platform stage "
            "train without waiting for repository CI"
        ),
        "stages": _hosted_release_stages(
            workflow="platform-release-bridge.yml",
            target_environment="stage",
            release_mode="normal",
            product_bridge=True,
            wait_for_ci=False,
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
        "status": FLOW_STATUS_DISABLED,
        "done_description": "Platform release completed through the hosted production train",
    },
    {
        "id": "platform-production-independent",
        "project": "platform",
        "name": "Production Independent",
        "description": "Release Platform main directly to hosted production",
        "stages": _hosted_release_stages(
            workflow="platform-release.yml",
            target_environment="production",
            release_mode="normal",
            product_bridge=False,
            independent_environment=True,
        ),
        "on_failure": "halt",
        "target_env": "production",
        "status": FLOW_STATUS_ACTIVE,
        "done_description": "Platform release completed in hosted production",
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
        "id": BUZZ_PRODUCTION_RELEASE_FLOW_ID,
        "project": "buzz",
        "name": "Production Release",
        "description": (
            "Deploy production through GitHub Actions environment protection, "
            "then run smoke verification"
        ),
        "stages": _BUZZ_RELEASE_STAGES,
        "on_failure": "halt",
        "target_env": "production",
        "status": FLOW_STATUS_ACTIVE,
        "done_description": "Deployed to production and smoke checks passed",
    },
    {
        "id": BUZZ_PRODUCTION_HOTFIX_FLOW_ID,
        "project": "buzz",
        "name": "Production Hotfix",
        "description": (
            "Deploy a hotfix directly to production through GitHub Actions, "
            "then run smoke verification"
        ),
        "stages": _BUZZ_HOTFIX_STAGES,
        "on_failure": "halt",
        "target_env": "production",
        "status": FLOW_STATUS_ACTIVE,
        "done_description": (
            "Hotfix deployed to production and smoke checks passed"
        ),
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


BUILTIN_FLOW_SUPERSESSIONS = (
    {
        "predecessor_id": "buzz-prod-release",
        "successor_id": BUZZ_PRODUCTION_RELEASE_FLOW_ID,
        "recognized_definitions": (
            {
                "name": "Prod Release",
                "description": (
                    "Push-to-main triggers prod deploy via GitHub Actions with "
                    "environment protection gate, then smoke test"
                ),
                "stages": _BUZZ_RELEASE_STAGES,
                "on_failure": "halt",
                "target_env": "production",
                "done_description": (
                    "Deployed to production and smoke checks passed"
                ),
            },
            {
                "name": "Sprint Release",
                "description": (
                    "Verify ephemeral deploy, approval gate, prod deploy via "
                    "GitHub Actions, then smoke test"
                ),
                "stages": _BUZZ_RELEASE_WITH_LOCAL_APPROVAL_STAGES,
                "on_failure": "halt",
                "target_env": "production",
                "done_description": (
                    "Deployed to production and smoke checks passed"
                ),
            },
        ),
    },
    {
        "predecessor_id": "buzz-prod-hotfix",
        "successor_id": BUZZ_PRODUCTION_HOTFIX_FLOW_ID,
        "recognized_definitions": tuple(
            {
                "name": name,
                "description": (
                    "Manual dispatch of hotfix workflow for direct-to-prod deploy"
                ),
                "stages": _BUZZ_HOTFIX_PREDECESSOR_STAGES,
                "on_failure": "halt",
                "target_env": "production",
                "done_description": "Hotfix deployed to production",
            }
            for name in ("Prod Hotfix", "Hotfix")
        ),
    },
)


__all__ = [
    "BUILTIN_FLOW_SUPERSESSIONS",
    "BUZZ_PRODUCTION_HOTFIX_FLOW_ID",
    "BUZZ_PRODUCTION_RELEASE_FLOW_ID",
    "SEED_FLOWS",
]
