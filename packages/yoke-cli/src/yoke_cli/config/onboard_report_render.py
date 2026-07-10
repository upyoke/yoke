"""Human-readable rendering for onboarding reports."""

from __future__ import annotations

from typing import Any, Dict

from yoke_cli.config import onboard_project, onboard_reuse_feedback
from yoke_contracts.machine_config.schema import POSTGRES_TRANSPORTS

_REUSE_GROUP_LABELS = (
    ("On this machine (~/.yoke)", "machine"),
    ("In the Yoke core database", "core"),
    ("In your project folder", "repo"),
    ("Advanced / admin", "admin"),
)


def render_human(report: Dict[str, Any]) -> str:
    """Render an onboarding report for terminal display."""
    lines = [
        "Yoke onboard",
        f"  mode: {report['mode']}",
        f"  project mode: {report.get('project_mode', onboard_project.PROJECT_MODE_MACHINE_ONLY)}",
        f"  config: {report['config_path']}",
        f"  applied: {str(report['applied']).lower()}",
        "",
        "Write plan:",
    ]
    for step in report["plan"]["steps"]:
        lines.append(f"  - {step['action']}: {step['target']}")
    reuse_groups = onboard_reuse_feedback.grouped_lines_for_plan(report)
    labels = _reuse_group_labels_for_report(report)
    if any(reuse_groups.get(key) for _label, key in labels):
        lines.extend(["", "Already detected / reused:"])
        for label, key in labels:
            grouped_lines = reuse_groups.get(key, [])
            if not grouped_lines:
                continue
            lines.append(f"  {label}:")
            lines.extend(f"    - {line}" for line in grouped_lines)
    identity = report["identity"]
    if identity.get("checked"):
        lines.extend(["", f"Identity check: {identity.get('status')}"])
    machine_github = report.get("machine_github")
    if isinstance(machine_github, dict):
        lines.extend(["", f"Machine GitHub: {machine_github.get('choice')}"])
    project_report = report.get("project_onboarding")
    if isinstance(project_report, dict):
        _append_project_handoff(lines, project_report)
    lines.extend(["", "Next steps:"])
    lines.extend(f"  - {step}" for step in report["next_steps"])
    lines.append("")
    if not report["applied"]:
        lines.extend(["Rerun with --yes to apply this plan.", ""])
    return "\n".join(lines)


def _reuse_group_labels_for_report(report: Dict[str, Any]) -> tuple[tuple[str, str], ...]:
    plan = report.get("plan") if isinstance(report, dict) else None
    connection = plan.get("connection") if isinstance(plan, dict) else None
    if not isinstance(connection, dict):
        return _REUSE_GROUP_LABELS
    if str(connection.get("transport") or "") not in POSTGRES_TRANSPORTS:
        return _REUSE_GROUP_LABELS
    return tuple(
        ("In the local Yoke database", key) if key == "core" else (label, key)
        for label, key in _REUSE_GROUP_LABELS
    )


def _append_project_handoff(lines: list[str], project_report: dict[str, Any]) -> None:
    lines.extend(["", "Project handoff:"])
    lines.append(f"  operation: {project_report.get('operation')}")
    checkout = project_report.get("checkout")
    if isinstance(checkout, dict):
        lines.append(f"  checkout: {checkout.get('path')}")
    lines.append(f"  applied: {str(project_report.get('applied')).lower()}")
    handoff = project_report.get("handoff")
    if isinstance(handoff, dict):
        lines.append(f"  run id: {handoff.get('run_id')}")
        lines.append(f"  next: {handoff.get('agent_command')}")
    _append_clone_resume(lines, project_report)


def _append_clone_resume(lines: list[str], project_report: dict[str, Any]) -> None:
    """Append concrete reuse details when a clone apply resumes prior work."""
    resume = project_report.get("clone_resume")
    if not isinstance(resume, dict) or not any(resume.values()):
        return
    project = project_report.get("project")
    project = project if isinstance(project, dict) else {}
    checkout = project_report.get("checkout")
    checkout = checkout if isinstance(checkout, dict) else {}
    lines.extend(["", "Resumed from a prior run:"])
    if resume.get("clone_reused"):
        lines.append(f"  - Reused your existing clone at {checkout.get('path')}")
    if resume.get("repo_reused"):
        lines.append(f"  - Repo {project.get('github_repo')} already existed — reused")
    if resume.get("origin_rehomed"):
        lines.append(
            f"  - Re-pushed {project.get('default_branch')} "
            "(resuming a prior run)"
        )


__all__ = ["render_human"]
