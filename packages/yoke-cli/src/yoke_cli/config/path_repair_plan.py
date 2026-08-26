"""Serializable PATH repair plan shared by direct fix and onboarding Review."""

from __future__ import annotations

from typing import Any, Iterable

from yoke_cli.config import path_doctor


LOGIN_SURFACE = "login"
SSH_SURFACE = "ssh"


def build(diagnosis: path_doctor.PathDiagnosis) -> dict[str, Any]:
    targets = []
    if diagnosis.login_needs_fix:
        targets.append({"surface": LOGIN_SURFACE, "path": diagnosis.startup_file})
    if diagnosis.ssh_startup_file and diagnosis.ssh_needs_fix:
        targets.append({"surface": SSH_SURFACE, "path": diagnosis.ssh_startup_file})

    managed_path_dirs = tuple(
        dict.fromkeys((diagnosis.tool_bin_dir, *diagnosis.managed_path_dirs))
    )
    directory_tools = {directory: [] for directory in managed_path_dirs}
    directory_tools.setdefault(diagnosis.tool_bin_dir, []).extend(path_doctor.TOOLS)
    for resolution in diagnosis.harness_clis:
        if resolution.directory:
            directory_tools.setdefault(resolution.directory, []).append(
                resolution.executable
            )
    return {
        "shell": diagnosis.current_shell,
        "tool_bin_dir": diagnosis.tool_bin_dir,
        "login_file": diagnosis.startup_file,
        "ssh_file": diagnosis.ssh_startup_file or None,
        "directories": list(managed_path_dirs),
        "directory_tools": {
            directory: list(dict.fromkeys(names))
            for directory, names in directory_tools.items()
        },
        "harness_clis": [resolution.to_json() for resolution in diagnosis.harness_clis],
        "unresolved_harness_clis": [
            resolution.executable
            for resolution in diagnosis.harness_clis
            if not resolution.path
        ],
        "targets": targets,
    }


def target_paths(plan: dict[str, Any]) -> list[str]:
    return [str(target["path"]) for target in plan.get("targets", [])]


def required_tools(plan: dict[str, Any]) -> tuple[str, ...]:
    installed_harnesses = [
        str(row["executable"])
        for row in plan.get("harness_clis", [])
        if row.get("path")
    ]
    return tuple(dict.fromkeys(["yoke", "uv", *installed_harnesses]))


def verification_ok(resolved: Iterable[Any], plan: dict[str, Any]) -> bool:
    by_name = {str(row.name): row.path for row in resolved}
    return all(by_name.get(name) for name in required_tools(plan))


def directory_summary(plan: dict[str, Any]) -> str:
    grouped = []
    directory_tools = plan.get("directory_tools", {})
    tool_bin_dir = str(plan.get("tool_bin_dir") or "")
    unresolved = [str(name) for name in plan.get("unresolved_harness_clis", [])]
    for directory in plan.get("directories", []):
        names = [str(name) for name in directory_tools.get(directory, [])]
        detail = ", ".join(names) if names else "managed tools"
        if directory == tool_bin_dir and unresolved:
            detail += "; standard location for later installs: " + ", ".join(
                unresolved
            )
        grouped.append(f"{directory} ({detail})")
    return "; ".join(grouped)


def target_description(target: dict[str, Any], plan: dict[str, Any]) -> str:
    path = str(target.get("path") or "")
    directories = directory_summary(plan)
    if target.get("surface") == SSH_SURFACE:
        login_file = str(plan.get("login_file") or "the login startup file")
        return (
            f"Write {path} for non-login/SSH shells: prepend {directories}. "
            f"SSH is separate because it never reads {login_file}."
        )
    return f"Write {path} for login shells: prepend {directories}."


def description_lines(plan: dict[str, Any]) -> list[str]:
    lines = [target_description(target, plan) for target in plan.get("targets", [])]
    missing = [str(name) for name in plan.get("unresolved_harness_clis", [])]
    if missing:
        lines.append(
            "Not installed yet: "
            + ", ".join(missing)
            + ". The standard tool directory is ready; rerun `yoke path fix` "
            "if a later vendor install lands elsewhere."
        )
    return lines


__all__ = [
    "LOGIN_SURFACE",
    "SSH_SURFACE",
    "build",
    "description_lines",
    "directory_summary",
    "required_tools",
    "target_description",
    "target_paths",
    "verification_ok",
]
