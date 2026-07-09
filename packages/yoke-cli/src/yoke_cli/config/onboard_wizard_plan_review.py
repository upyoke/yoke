"""Write-plan classification for the onboarding wizard's Finish preview.

The classifier buckets ``build_report``'s write-plan steps into machine /
Yoke-core-database / repo-local / source-dev-admin groups and renders each step
as a plain "what (and where/why)" line, so the review screen names what every
write means instead of echoing the internal action/target ids. Consumed by
``onboard_wizard_steps.finish_body`` (re-exported there as ``classify_plan`` /
``render_write_plan`` / ``_friendly_line``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from yoke_cli.config import onboard_project
from yoke_cli.config import onboard_reuse_feedback
from yoke_cli.config.onboard_plan_labels import friendly_line as _friendly_line
from yoke_contracts.machine_config.schema import POSTGRES_TRANSPORTS

if TYPE_CHECKING:  # pragma: no cover - typing only
    from textual.widgets import Static

_PLAN_GROUPS = (
    ("On this machine (~/.yoke)", "onboard-plan-group-machine", "machine"),
    ("In the Yoke core database", "onboard-plan-group-core", "core"),
    ("In your project folder", "onboard-plan-group-repo", "repo"),
    ("Advanced / admin", "onboard-plan-group-admin", "admin"),
)
# Distinct labels for the "already set up, Apply reuses these" block so it is not
# confused with the write-plan groups above (which share the same locations).
_REUSE_GROUPS = (
    ("Already on this machine (~/.yoke)", "onboard-plan-group-machine", "machine"),
    ("Already in the Yoke core database", "onboard-plan-group-core", "core"),
    ("Already in your project folder", "onboard-plan-group-repo", "repo"),
    ("Already set up (advanced / admin)", "onboard-plan-group-admin", "admin"),
)

_MACHINE_ACTIONS = {
    "create-or-validate-dir", "set-active-env", "set-https-api-url",
    "local-universe-init",
    "store-token-reference", "machine-github-connection", "create-runtime-dir",
    "project-checkout-register",
}
_REPO_ACTIONS = {
    "project-create-checkout", "project-clone-remote",
    "project-import-remote", "project-onboard-local-checkout",
    "project-rehome-push", "project-fork-remotes",
    "project-install-scaffold", "project-refresh-scaffold",
    "project-write-board-art",
}
_CORE_ACTIONS = {
    "project-source-choice", "project-github-auth-choice", "project-onboard",
}

def render_write_plan(plan: dict[str, Any]) -> list[Static]:
    from textual.widgets import Static

    grouped = classify_plan(plan)
    widgets: list[Static] = []
    for label, css_class, key in _groups_for_plan(plan, reuse=False):
        lines = grouped.get(key, [])
        if not lines:
            continue
        widgets.append(Static(label, classes=css_class))
        widgets.extend(
            Static(f"  • {line}", classes="onboard-plan-line") for line in lines
        )
    if not widgets:
        widgets.append(
            Static("No persistent writes planned.", classes="onboard-plan-line")
        )
    return widgets


def render_reuse_summary(plan: dict[str, Any]) -> list[Static]:
    from textual.widgets import Static

    grouped = onboard_reuse_feedback.grouped_lines_for_plan(plan)
    groups = _groups_for_plan(plan, reuse=True)
    if not any(grouped.get(key) for _label, _css, key in groups):
        return []
    widgets: list[Static] = []
    for label, css_class, key in groups:
        lines = grouped.get(key, [])
        if not lines:
            continue
        widgets.append(Static(label, classes=css_class))
        widgets.extend(
            Static(f"  • {line}", classes="onboard-plan-line") for line in lines
        )
    return widgets


def classify_plan(plan: dict[str, Any]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {
        "machine": [],
        "core": [],
        "repo": [],
        "admin": [],
    }
    inner = plan.get("plan", {}) if isinstance(plan, dict) else {}
    steps = inner.get("steps", [])
    project = inner.get("project") or {}
    raw_name = str(project.get("name") or "").strip()
    project_name = "" if raw_name == "None" else raw_name
    is_admin = plan.get("project_mode") == onboard_project.PROJECT_MODE_SOURCE_DEV_ADMIN
    for step in steps:
        action = str(step.get("action", ""))
        target = str(step.get("target", ""))
        if action == "stop-before-project-or-github":
            continue
        text = _friendly_line(action, target, project_name)
        if action in _MACHINE_ACTIONS:
            grouped["machine"].append(text)
        elif action == "project-source-dev-admin" or (is_admin and action in _REPO_ACTIONS):
            grouped["admin"].append(text)
        elif action in _REPO_ACTIONS:
            grouped["repo"].append(text)
        elif action in _CORE_ACTIONS:
            grouped["core"].append(text)
        else:
            grouped["core"].append(text)
    return grouped


def _groups_for_plan(
    plan: dict[str, Any],
    *,
    reuse: bool,
) -> tuple[tuple[str, str, str], ...]:
    groups = _REUSE_GROUPS if reuse else _PLAN_GROUPS
    if not _uses_local_database(plan):
        return groups
    replacement = (
        "Already in the local Yoke database"
        if reuse else
        "In the local Yoke database"
    )
    return tuple(
        (replacement, css, key) if key == "core" else (label, css, key)
        for label, css, key in groups
    )


def _uses_local_database(plan: dict[str, Any]) -> bool:
    inner = plan.get("plan", {}) if isinstance(plan, dict) else {}
    connection = inner.get("connection") if isinstance(inner, dict) else None
    if not isinstance(connection, dict):
        return False
    return str(connection.get("transport") or "") in POSTGRES_TRANSPORTS


__all__ = ["classify_plan", "render_reuse_summary", "render_write_plan"]
