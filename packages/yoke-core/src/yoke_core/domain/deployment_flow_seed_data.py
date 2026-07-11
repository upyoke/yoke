"""Canonical built-in deployment flow seed rows."""

from __future__ import annotations

import json

from yoke_contracts.github_workflow_dispatch import (
    WORKFLOW_DISPATCH_CORRELATION_INPUT,
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
        "done_description": "Yoke core deployed to stage, health check passed, and stage installer distribution published",
    },
    {
        "id": "yoke-ephemeral-deploy", "project": "yoke", "name": "Ephemeral Deploy",
        "description": "Deploy a branch/SHA Yoke core preview environment through the shared ephemeral substrate (unmerged worktree branches; no merged gate)",
        "stages": json.dumps([
            {"name": "ephemeral-deploy", "executor": "ephemeral-deploy"},
            {"name": "complete", "executor": "auto"},
        ]),
        "on_failure": "halt", "target_env": "ephemeral",
        "done_description": "Yoke core preview environment deployed",
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
        "done_description": "Merged to main",
    },
]


__all__ = ["SEED_FLOWS"]
