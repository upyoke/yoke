"""Unknown machine settings warn without disabling commands or hooks."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any, Mapping

from yoke_contracts.machine_config.schema_projects import ValidationIssue, _warn

_ROOT_KEYS = frozenset(
    {
        "schema_version",
        "machine_id",
        "active_env",
        "connections",
        "temp_root",
        "cache_dir",
        "projects",
        "connection_projects",
        "settings",
        "github",
    }
)
_WARNED: set[tuple[str, str]] = set()


def unknown_key_issues(payload: Mapping[str, Any]) -> list[ValidationIssue]:
    """Inspect closed records; settings and provider-owned documents stay open."""
    from yoke_contracts.machine_config.retired_keys import RETIRED_MACHINE_CONFIG_KEYS
    from yoke_contracts.machine_config.schema_github import (
        GITHUB_ALLOWED_KEYS,
        GITHUB_AUTH_ALLOWED_KEYS,
    )
    from yoke_contracts.machine_config.schema_github_access import (
        GITHUB_INSTALLATION_ALLOWED_KEYS,
        GITHUB_REPOSITORY_ALLOWED_KEYS,
    )

    issues: list[ValidationIssue] = []

    def check(value, allowed, prefix):
        if not isinstance(value, Mapping):
            return
        for key in sorted(set(value) - set(allowed)):
            path = f"{prefix}.{key}" if prefix else str(key)
            issues.append(
                _warn(
                    "machine_config_key_unknown",
                    f"unknown key {path!r} is ignored",
                    path=path,
                    hint="Remove the key or use a release that supports it; retry the command.",
                )
            )

    check(payload, _ROOT_KEYS | RETIRED_MACHINE_CONFIG_KEYS.keys(), "")

    def check_projects(projects, prefix):
        if isinstance(projects, list):
            for index, entry in enumerate(projects):
                check(entry, {"checkout", "project_id"}, f"{prefix}[{index}]")

    check_projects(payload.get("projects"), "projects")
    groups = payload.get("connection_projects")
    if isinstance(groups, Mapping):
        for connection, projects in groups.items():
            check_projects(projects, f"connection_projects.{connection}")
    github = payload.get("github")
    check(github, GITHUB_ALLOWED_KEYS, "github")
    if isinstance(github, Mapping):
        check(
            github.get("authorization"),
            GITHUB_AUTH_ALLOWED_KEYS,
            "github.authorization",
        )
        for field, allowed in (
            ("installations", GITHUB_INSTALLATION_ALLOWED_KEYS),
            ("repositories", GITHUB_REPOSITORY_ALLOWED_KEYS),
        ):
            entries = github.get(field)
            if isinstance(entries, list):
                for index, entry in enumerate(entries):
                    check(entry, allowed, f"github.{field}.{index}")
    return issues


def warn_unknown_keys(payload: Mapping[str, Any], selected: Path) -> None:
    """Emit each file/key once per process, shared by CLI and hook readers."""
    for issue in unknown_key_issues(payload):
        identity = (str(selected), issue.path)
        if identity in _WARNED:
            continue
        _WARNED.add(identity)
        print(
            f"yoke: warning: {issue.code}: {selected}: {issue.message}. {issue.hint}",
            file=sys.stderr,
        )
