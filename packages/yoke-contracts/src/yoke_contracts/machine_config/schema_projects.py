"""Project-entry contract + shared issue primitives.

Each connection has one machine-local checkout per project.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

from yoke_contracts.machine_config.checkout import main_checkout

from yoke_contracts.machine_config.schema_connections import (
    MachineConfigContractError,
)


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    code: str
    message: str
    path: str = ""
    hint: str = ""

    def as_dict(self) -> dict[str, str]:
        data = {"severity": self.severity, "code": self.code, "message": self.message}
        if self.path:
            data["path"] = self.path
        if self.hint:
            data["hint"] = self.hint
        return data


def project_entry_for_checkout(
    payload: Mapping[str, Any],
    repo_root: str | Path,
) -> dict[str, Any]:
    """Return this checkout's project id on the selected connection."""
    candidates = {_path_key(p) for p in checkout_path_candidates(repo_root)}
    for entry in projects_for_connection(payload):
        if _path_key(Path(entry["checkout"]).expanduser()) in candidates:
            return {"project_id": entry["project_id"]}
    return {}


def mapped_checkouts(payload: Mapping[str, Any]) -> list[tuple[str, int]]:
    """Return checkout and project id pairs on the selected connection."""
    return [
        (entry["checkout"], entry["project_id"])
        for entry in projects_for_connection(payload)
    ]


def project_connection(payload: Mapping[str, Any]) -> str:
    """Use the existing admin/HTTPS pairing as one universe's mapping key."""
    from yoke_contracts.machine_config.schema_connections import (
        selected_env,
        same_universe_https_env,
    )

    env = selected_env(payload)
    return same_universe_https_env(payload, env) or env


def connection_project_maps(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Read the optional namespace map with one named shape refusal."""
    groups = payload.get("connection_projects")
    if groups is None:
        return {}
    if not isinstance(groups, Mapping):
        raise MachineConfigContractError(
            "connection_projects_invalid: set connection_projects to an object "
            "mapping connection labels to checkout entries, then retry"
        )
    return groups


def projects_for_connection(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Filter before interpreting a universe-local numeric project id."""
    groups = connection_project_maps(payload)
    if not groups:
        return []
    return normalize_projects(groups.get(project_connection(payload)))


def normalize_projects(projects: Any) -> list[dict[str, Any]]:
    """Return the canonical list of checkout and project id entries."""
    from yoke_contracts.machine_config.schema_project_validation import (
        validate_projects,
    )

    issues = [
        issue for issue in validate_projects(projects) if issue.severity == "error"
    ]
    if issues:
        issue = issues[0]
        raise MachineConfigContractError(
            f"{issue.code}: {issue.message}; {issue.hint or 'repair projects in machine config and retry'}"
        )
    return [
        {"checkout": entry["checkout"].strip(), "project_id": int(entry["project_id"])}
        for entry in (projects or [])
    ]


def existing_checkout_for_slot(
    projects: Any,
    *,
    checkout: str,
    project_id: int,
) -> Optional[str]:
    """Return the other checkout already registered for this project."""
    checkout_key = _path_key(Path(checkout).expanduser())
    for entry in normalize_projects(projects):
        if entry["project_id"] == int(project_id) and (
            _path_key(Path(entry["checkout"]).expanduser()) != checkout_key
        ):
            return entry["checkout"]
    return None


def upsert_project_entry(
    projects: Any,
    *,
    checkout: str,
    project_id: int,
) -> list[dict[str, Any]]:
    """Set the project's single checkout, replacing an authorized move."""
    checkout_key = _path_key(Path(checkout).expanduser())
    kept = [
        entry
        for entry in normalize_projects(projects)
        if entry["project_id"] != int(project_id)
        and _path_key(Path(entry["checkout"]).expanduser()) != checkout_key
    ]
    return [*kept, {"checkout": checkout, "project_id": int(project_id)}]


def checkout_path_candidates(repo_root: str | Path) -> list[Path]:
    root = Path(repo_root).expanduser()
    candidates = [root, *root.parents]
    try:
        candidates.append(root.resolve())
        candidates.extend(root.resolve().parents)
    except OSError:
        pass
    candidates.append(main_checkout(root))
    seen: set[str] = set()
    out: list[Path] = []
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            out.append(candidate)
            seen.add(key)
    return out


def normalize_project_id(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        project_id = int(value)
    except (TypeError, ValueError):
        return None
    return project_id if project_id > 0 else None


def _path_key(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _nonempty_str(value: Any, default: str) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else default


def _error(
    code: str, message: str, *, path: str = "", hint: str = ""
) -> ValidationIssue:
    return ValidationIssue("error", code, message, path=path, hint=hint)


def _warn(
    code: str, message: str, *, path: str = "", hint: str = ""
) -> ValidationIssue:
    return ValidationIssue("warning", code, message, path=path, hint=hint)
