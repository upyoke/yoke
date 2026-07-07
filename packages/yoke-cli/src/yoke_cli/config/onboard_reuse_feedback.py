"""Human-facing reuse notes for ``yoke onboard`` plans."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_cli.config import existing_project_lookup
from yoke_cli.config import onboard_project

_GROUP_ORDER = ("machine", "core", "repo", "admin")


def lines_for_plan(plan: Mapping[str, Any]) -> list[str]:
    """Return short notes for already-detected onboard state."""
    grouped = grouped_lines_for_plan(plan)
    return [
        line
        for key in _GROUP_ORDER
        for line in grouped.get(key, [])
    ]


def grouped_lines_for_plan(plan: Mapping[str, Any]) -> dict[str, list[str]]:
    """Return already-detected onboard state grouped by storage surface."""
    inner = _inner_plan(plan)
    reuse = inner.get("reuse")
    grouped: dict[str, list[str]] = {
        "machine": [],
        "core": [],
        "repo": [],
        "admin": [],
    }
    if not isinstance(reuse, Mapping):
        return grouped
    project = inner.get("project")
    project = project if isinstance(project, Mapping) else {}
    machine = grouped["machine"]
    core = grouped["core"]
    repo_lines = grouped["repo"]
    env = str(inner.get("active_env") or "").strip()
    connection = inner.get("connection")
    connection = connection if isinstance(connection, Mapping) else {}
    api_url = str(connection.get("api_url") or "").strip()

    if reuse.get("yoke_home"):
        machine.append("Yoke home folder already exists.")
    if reuse.get("connection") and reuse.get("token_reference"):
        target = f" for {env}" if env else ""
        endpoint = f" at {api_url}" if api_url else ""
        machine.append(
            f"Yoke API connection and token are already saved{target}{endpoint}."
        )
    else:
        if reuse.get("connection"):
            endpoint = f" at {api_url}" if api_url else ""
            machine.append(f"Yoke API connection is already saved{endpoint}.")
        if reuse.get("token_reference"):
            machine.append("Yoke API token file is already saved.")
    if reuse.get("active_env") and not reuse.get("connection"):
        target = f" {env}" if env else ""
        machine.append(f"Active environment is already{target}.")
    if reuse.get("machine_github"):
        machine.append("Local GitHub credential is already saved in ~/.yoke/secrets.")
    if reuse.get("temp_root") and reuse.get("cache_dir"):
        machine.append("Runtime scratch and cache folders already exist.")
    else:
        if reuse.get("temp_root"):
            machine.append("Runtime scratch folder already exists.")
        if reuse.get("cache_dir"):
            machine.append("Runtime cache folder already exists.")

    project_name = _project_name(project)
    project_id = _project_id(project)
    if reuse.get("project_identity"):
        _append_existing_project_identity(
            grouped,
            project=project,
            project_name=project_name,
            project_id=project_id,
        )
    if reuse.get("project_checkout"):
        checkout = str(project.get("checkout") or "").strip()
        target = f" at {checkout}" if checkout else ""
        machine.append(
            f"Checkout mapping is already registered in ~/.yoke/config.json{target}."
        )
    if reuse.get("project_clone_checkout"):
        checkout = str(project.get("checkout") or "").strip()
        target = f" at {checkout}" if checkout else ""
        repo_lines.append(
            f"Matching clone already exists{target}; Apply will reuse it."
        )
    _append_default_branch_lines(grouped, project)
    if reuse.get("project_existing_remote"):
        repo = str(project.get("github_repo") or "").strip()
        if repo and repo != "None":
            repo_lines.append(f"Using this checkout's existing GitHub remote: {repo}.")
        else:
            repo_lines.append("Using this checkout's existing git remote.")
    if reuse.get("project_github_auth"):
        if reuse.get("project_identity"):
            core.append("Project GitHub settings come from the Yoke core database.")
        elif not reuse.get("project_existing_remote"):
            core.append("Project GitHub settings are already available.")
    if reuse.get("project_scaffold"):
        repo_lines.append("Project scaffold is already installed; Apply will refresh it.")
    return grouped


def _inner_plan(plan: Mapping[str, Any]) -> Mapping[str, Any]:
    nested = plan.get("plan")
    if isinstance(nested, Mapping):
        return nested
    return plan


def _project_name(project: Mapping[str, Any]) -> str:
    name = str(project.get("name") or "").strip()
    if name and name != "None":
        return name
    slug = str(project.get("slug") or "").strip()
    if slug and slug != "None":
        return slug
    return "selected project"


def _project_id(project: Mapping[str, Any]) -> str:
    raw = project.get("existing_project_id")
    if raw is None:
        return ""
    text = str(raw).strip()
    return text if text and text != "None" else ""


def _append_existing_project_identity(
    grouped: dict[str, list[str]],
    *,
    project: Mapping[str, Any],
    project_name: str,
    project_id: str,
) -> None:
    suffix = f" (id {project_id})" if project_id else ""
    source = str(project.get("existing_project_match_source") or "").strip()
    local_source = str(project.get("existing_project_local_source") or "").strip()
    repo = str(project.get("github_repo") or "").strip()
    if source == existing_project_lookup.MATCH_SOURCE_LOCAL_CHECKOUT:
        local_label = local_source or "local checkout metadata"
        label = f"project id {project_id}" if project_id else "a project id"
        grouped["machine"].append(
            f"Local project metadata matched {label} from {local_label}."
        )
        grouped["core"].append(
            f"Yoke core database verified existing project: {project_name}{suffix}."
        )
    elif source == existing_project_lookup.MATCH_SOURCE_GITHUB_REPO:
        repo_label = repo if repo and repo != "None" else "the GitHub repo"
        grouped["core"].append(
            "Yoke core database matched existing project by GitHub repo: "
            f"{repo_label}{suffix}."
        )
        grouped["machine"].append(
            "No local Yoke project metadata was used for the existing-project match."
        )
    else:
        grouped["core"].append(
            f"Existing Yoke project detected in the Yoke core database: "
            f"{project_name}{suffix}."
        )
    _append_existing_project_metadata_lines(grouped["core"], project)


def _append_existing_project_metadata_lines(
    lines: list[str],
    project: Mapping[str, Any],
) -> None:
    repo = str(project.get("github_repo") or "").strip()
    if repo and repo != "None":
        lines.append(f"Existing project GitHub repo in the Yoke core database: {repo}.")
    prefix = str(project.get("public_item_prefix") or "").strip()
    if prefix and prefix != "None":
        lines.append(
            f"Existing project issue prefix in the Yoke core database: {prefix}."
        )


def _append_default_branch_lines(
    grouped: dict[str, list[str]],
    project: Mapping[str, Any],
) -> None:
    branch = str(project.get("default_branch") or "").strip()
    if not branch or branch == "None":
        return
    source = str(project.get("default_branch_source") or "").strip()
    if source == onboard_project.DEFAULT_BRANCH_SOURCE_EXISTING_PROJECT:
        grouped["core"].append(
            f"Existing project default branch in the Yoke core database: {branch}."
        )
        return
    if source == onboard_project.DEFAULT_BRANCH_SOURCE_SOURCE_REPO:
        grouped["repo"].append(f"Using detected source default branch: {branch}.")
        return
    if source == onboard_project.DEFAULT_BRANCH_SOURCE_SOURCE_FALLBACK:
        grouped["repo"].append(
            f"Using default branch {branch}; the source did not report one.",
        )


__all__ = ["grouped_lines_for_plan", "lines_for_plan"]
