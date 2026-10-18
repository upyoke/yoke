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
