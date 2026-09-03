"""Write the project half of an applied onboarding onto the apply report.

Machine onboarding writes a connection and a machine identity; a run that also
names a project owes three further facts about that project — the handoff
itself, the hosting posture the operator answered, and the ``aws-admin``
capability row that posture implies. All three are available at the same
moment, are skipped by the same machine-only condition, and are meaningless
apart from one another, so they land together here rather than as three tails
on the machine report builder.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Mapping

from yoke_cli.config import onboard_apply_aws_admin_capability
from yoke_cli.config import onboard_apply_hosting_posture
from yoke_cli.config import onboard_apply_progress
from yoke_cli.config import onboard_bridge
from yoke_cli.config import onboard_report

#: Report message a run that reached the project handoff replaces its
#: machine-only message with.
APPLIED_MESSAGE = "machine config and project handoff written"


def apply(
    report: Dict[str, Any],
    *,
    error_cls: type[Exception],
    config_path: Path,
    project_mode: str,
    project_inputs: Mapping[str, Any],
    reuse: Mapping[str, Any],
    progress: onboard_apply_progress.ProgressCallback | None,
    service_api_url: str | None,
    local_connection_selected: bool,
    project_slug: str | None,
    hosting_choice: str,
    hosting_provider_note: str | None,
    hosting_verification: Mapping[str, Any] | None,
) -> None:
    """Record the applied project handoff, hosting posture, and AWS row."""
    if not reuse.get("project_identity"):
        onboard_apply_progress.emit(
            progress,
            "project-source-choice",
            onboard_report.source_choice_target(project_mode, project_inputs),
            "done",
        )
    report["project_onboarding"] = onboard_bridge.project_report(
        error_cls=error_cls,
        config_path=config_path,
        apply=True,
        project_inputs=project_inputs,
        reuse=reuse,
        progress=progress,
        service_api_url=service_api_url,
        local_connection_selected=local_connection_selected,
    )
    slug = str(project_slug or "")
    report["hosting_posture"] = onboard_apply_hosting_posture.record(
        project=slug,
        posture=hosting_choice,
        provider_note=hosting_provider_note,
        config_path=config_path,
    )
    report["aws_admin_capability"] = onboard_apply_aws_admin_capability.record(
        project=slug,
        posture=hosting_choice,
        verification=hosting_verification,
        config_path=config_path,
    )
    report["message"] = APPLIED_MESSAGE


__all__ = ["APPLIED_MESSAGE", "apply"]
