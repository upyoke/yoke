"""Assemble the onboarding kwargs and hand them to the durable apply.

Carved out of the ``yoke onboard`` adapter, which stays a command surface:
this is the pass-through naming every input the wizard and the flag route
share, so the adapter does not carry a hundred-line parameter list beside
its argument parsing.
"""

from __future__ import annotations

import sys

from yoke_cli.commands.adapters import onboard_apply
from yoke_cli.config import onboard as onboard_config
from yoke_cli.config import onboard_apply_report
from yoke_cli.config import onboard_destinations
from yoke_cli.config import onboard_wizard
from yoke_cli.config.onboard_error_friendly import friendly_permission_error
from yoke_cli.config.project_clone_support import ClonePlan
from yoke_cli.config.project_publish_support import PublishRequest
from yoke_cli.config.writer import MachineConfigWriteError
from yoke_contracts.machine_config.schema import MachineConfigContractError

_apply_with_durable_report = onboard_apply.apply_with_durable_report
_print_failure_summary = onboard_apply.print_failure_summary


def build_report(
    *,
    config_path: str | None,
    env_name: str,
    api_url: str,
    destination: str = onboard_destinations.DEFAULT_DESTINATION,
    token: str | None,
    token_file: str | None,
    token_source_kind: str,
    mode: str,
    apply: bool,
    check_identity: bool,
    machine_github_choice: str,
    machine_github_api_url: str | None,
    project_mode: str,
    project_remote_url: str | None,
    project_checkout: str | None,
    project_slug: str | None,
    project_name: str | None,
    project_org: str | None,
    project_github_repo: str | None,
    project_github_repository_id: int | None = None,
    project_github_installation_id: int | None = None,
    project_default_branch: str | None,
    project_default_branch_source: str | None,
    project_public_item_prefix: str | None,
    existing_project_id: int | None,
    project_github_adoption: str | None,
    project_github_adoption_preserve: bool = False,
    existing_project_match_source: str | None = None,
    existing_project_local_source: str | None = None,
    project_publish: PublishRequest | None = None,
    project_clone: ClonePlan | None = None,
    project_keep_existing_remote: bool = False,
    resume_run_id: str | None = None,
    resume_payload: dict | None = None,
    harness_posture: bool = True,
) -> dict | None:
    try:
        return _apply_with_durable_report(
            {
                "config_path": config_path,
                "env_name": env_name,
                "api_url": api_url,
                "destination": destination,
                "token": token,
                "token_file": token_file,
                "token_source_kind": token_source_kind,
                "mode": mode,
                "apply": apply,
                "check_identity": check_identity,
                "harness_posture": harness_posture,
                "machine_github_choice": machine_github_choice,
                "machine_github_api_url": machine_github_api_url,
                "project_mode": project_mode,
                "project_remote_url": project_remote_url,
                "project_checkout": project_checkout,
                "project_slug": project_slug,
                "project_name": project_name,
                "project_org": project_org,
                "project_github_repo": project_github_repo,
                "project_github_repository_id": project_github_repository_id,
                "project_github_installation_id": project_github_installation_id,
                "project_default_branch": project_default_branch,
                "project_default_branch_source": project_default_branch_source,
                "project_public_item_prefix": project_public_item_prefix,
                "existing_project_id": existing_project_id,
                "existing_project_match_source": existing_project_match_source,
                "existing_project_local_source": existing_project_local_source,
                "project_github_adoption": project_github_adoption,
                "project_github_adoption_preserve": (project_github_adoption_preserve),
                "project_publish": project_publish,
                "project_clone": project_clone,
                "project_keep_existing_remote": project_keep_existing_remote,
                "resume_run_id": resume_run_id,
                "resume_payload": resume_payload,
            }
        )
    except (
        onboard_config.OnboardError,
        onboard_apply_report.OnboardApplyReportError,
        MachineConfigContractError,
        MachineConfigWriteError,
    ) as exc:
        print(f"error: {friendly_permission_error(str(exc))}", file=sys.stderr)
        return None
    except onboard_wizard.WizardApplyError as exc:
        _print_failure_summary(
            onboard_wizard.WizardRunResult(
                exit_code=1,
                error=str(exc),
                failed_step=exc.failed_step,
                report_path=exc.report_path,
                resume_command=exc.resume_command,
            )
        )
        return None


__all__ = ["build_report"]
