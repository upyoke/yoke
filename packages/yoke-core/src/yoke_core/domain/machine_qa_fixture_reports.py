"""Closed report payloads written by Machine QA fixture setup."""

from __future__ import annotations

from typing import Any, Mapping


def build_apply_resume_report(
    parameters: Mapping[str, Any],
    *,
    home: str,
) -> dict[str, Any]:
    """Build the secret-free failed report consumed by resume QA."""
    checkout = str(parameters["path"])
    config_path = f"{home}/.yoke/config.json"
    credentials = {
        "yoke": {
            "kind": "file",
            "path": parameters["token_path"],
        },
        "github_app": {
            "machine": {"kind": ""},
            "project": {
                "adoption": "backlog-only",
                "repo": "owner/apply-resume",
            },
        },
    }
    project = {
        "mode": "local-checkout",
        "remote_url": "",
        "checkout": checkout,
        "slug": "apply-resume",
        "name": "Apply Resume",
        "org": "",
        "github_repo": "owner/apply-resume",
        "default_branch": "main",
        "default_branch_source": "",
        "public_item_prefix": "APL",
        "existing_project_id": None,
        "existing_project_match_source": "",
        "existing_project_local_source": "",
        "github_adoption": "backlog-only",
        "github_binding": {
            "adoption": "backlog-only",
            "repo": "owner/apply-resume",
        },
        "keep_existing_remote": False,
        "publish": None,
        "clone": None,
    }
    timestamp = "2026-07-04T00:00:00Z"
    steps = [
        {
            "step_id": step_id,
            "action": step_id.split("-", 1)[1],
            "target": "",
            "label": step_id.split("-", 1)[1].replace("-", " "),
            "status": "done",
            "started_at": timestamp,
            "finished_at": timestamp,
            "error": None,
        }
        for step_id in parameters["completed_steps"]
    ]
    failed_step = "04-project-onboard-local-checkout"
    steps.append(
        {
            "step_id": failed_step,
            "action": "project-onboard-local-checkout",
            "target": checkout,
            "label": "Use the local checkout",
            "status": "failed",
            "started_at": timestamp,
            "finished_at": timestamp,
            "error": "transient failure",
        }
    )
    return {
        "schema": "yoke.onboard.apply-report",
        "schema_version": 1,
        "run_id": parameters["run_id"],
        "created_at": timestamp,
        "updated_at": timestamp,
        "package_version": "recipe",
        "config_path": config_path,
        "env": "stage",
        "api_url": parameters["api_url"],
        "checkout_path": checkout,
        "source_repo": "",
        "target_github_repo": "owner/apply-resume",
        "credential_sources": credentials,
        "input_snapshot": {
            "config_path": config_path,
            "env_name": "stage",
            "api_url": parameters["api_url"],
            "destination": "",
            "mode": "quick",
            "check_identity": False,
            "credential_sources": credentials,
            "machine_github": {
                "choice": "skip",
                "api_url": "",
                "authorization_source": {"kind": ""},
            },
            "project": project,
            "checkout_provenance": {
                "path": checkout,
                "project_mode": "local-checkout",
                "existed_before_apply": True,
                "created_by_run": False,
                "safe_to_preserve_for_new_target": False,
            },
        },
        "steps": steps,
        "final_status": "failed",
        "failed_step": failed_step,
        "error": "transient failure",
        "resume_command": f"yoke onboard --resume {parameters['run_id']}",
        "new_target_hint": "Re-run to redo setup: yoke onboard",
        "secret_free": True,
    }


__all__ = ["build_apply_resume_report"]
