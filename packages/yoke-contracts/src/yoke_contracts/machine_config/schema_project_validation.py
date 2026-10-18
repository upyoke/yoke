"""Validate the machine-local, connection-scoped project checkout list."""

from typing import Any, Mapping

from yoke_contracts.machine_config.schema_projects import (
    ValidationIssue,
    normalize_project_id,
    _error,
    _is_nonempty_str,
)


def validate_projects(projects: Any) -> list[ValidationIssue]:
    """Require exactly one checkout entry per project."""
    if projects is None:
        return []
    if not isinstance(projects, list):
        return [
            _error(
                "projects_invalid",
                "projects must be a list of {checkout, project_id} entries",
                path="projects",
                hint="Set one checkout entry per project and retry.",
            )
        ]
    issues = []
    ids = set()
    checkouts = set()
    for index, entry in enumerate(projects):
        prefix = f"projects[{index}]"
        if not isinstance(entry, Mapping):
            issues.append(
                _error(
                    "project_entry_invalid",
                    "project entry must be an object",
                    path=prefix,
                )
            )
            continue
        for key in sorted(set(entry) - {"checkout", "project_id"}):
            issues.append(
                _error(
                    "project_key_invalid",
                    f"project entry does not support {key!r}",
                    path=f"{prefix}.{key}",
                )
            )
        checkout = entry.get("checkout")
        project_id = normalize_project_id(entry.get("project_id"))
        if not _is_nonempty_str(checkout):
            issues.append(
                _error(
                    "project_checkout_invalid",
                    "project entry requires a non-empty checkout path",
                    path=prefix,
                )
            )
        elif checkout in checkouts:
            issues.append(
                _error(
                    "project_checkout_duplicate",
                    "a checkout may map to only one project per connection",
                    path=prefix,
                )
            )
        else:
            checkouts.add(checkout)
        if project_id is None:
            issues.append(
                _error(
                    "project_id_required",
                    "project entry requires a positive integer project_id",
                    path=prefix,
                )
            )
        elif project_id in ids:
            issues.append(
                _error(
                    "project_id_duplicate",
                    "a project must have exactly one checkout per connection",
                    path=prefix,
                )
            )
        else:
            ids.add(project_id)
    return issues


def validate_connection_projects(groups: Any) -> list[ValidationIssue]:
    """Validate each independent connection's checkout namespace."""
    if groups is None:
        return []
    if not isinstance(groups, Mapping):
        return [
            _error(
                "connection_projects_invalid",
                "connection_projects must map connection labels to checkout lists",
                path="connection_projects",
                hint="Run yoke config example and repair the named map.",
            )
        ]
    issues = []
    for connection, projects in groups.items():
        if not _is_nonempty_str(connection):
            issues.append(
                _error(
                    "project_connection_required",
                    "connection label must be non-empty",
                    path="connection_projects",
                )
            )
        for issue in validate_projects(projects):
            issues.append(
                ValidationIssue(
                    issue.severity,
                    issue.code,
                    issue.message,
                    path=f"connection_projects.{connection}{issue.path.removeprefix('projects')}",
                    hint=issue.hint,
                )
            )
    return issues
