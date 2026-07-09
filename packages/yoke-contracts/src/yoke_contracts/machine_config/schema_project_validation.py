"""Project-entry validation for the machine-config contract.

Split from :mod:`schema_projects` under the authored-file cap. Depends
one-directionally on the shared primitives there (issue helpers, id
normalization); :mod:`schema_projects` imports nothing back.

Validates both the canonical flat-list shape and the legacy checkout-keyed
object shape, reporting issues against the raw payload.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.machine_config.schema_projects import (
    ValidationIssue,
    normalize_project_id,
    _error,
    _is_nonempty_str,
    _warn,
)


def validate_projects(
    projects: Any,
    *,
    connection_labels: frozenset[str] | set[str] = frozenset(),
) -> list[ValidationIssue]:
    """Validate the ``projects`` container and each entry."""
    if projects is None:
        return []
    if isinstance(projects, list):
        issues: list[ValidationIssue] = []
        for index, raw in enumerate(projects):
            checkout = raw.get("checkout") if isinstance(raw, Mapping) else None
            label = checkout if _is_nonempty_str(checkout) else f"[{index}]"
            issues.extend(_validate_project_entry(
                label, raw, in_list=True, connection_labels=connection_labels))
        return issues
    if isinstance(projects, Mapping):
        issues = []
        for checkout, raw in projects.items():
            issues.extend(_validate_project_entry(
                checkout, raw, in_list=False, connection_labels=connection_labels))
        return issues
    return [_error("projects_invalid",
                   "projects must be a list of {checkout, project_id, env} entries",
                   path="projects")]


def _validate_project_entry(
    checkout: Any,
    entry: Any,
    *,
    in_list: bool,
    connection_labels: frozenset[str] | set[str],
) -> list[ValidationIssue]:
    prefix = f"projects.{checkout}"
    if not isinstance(entry, Mapping):
        return [_error("project_entry_invalid", "project entry must be an object", path=prefix)]
    if not _is_nonempty_str(checkout):
        return [_error("project_checkout_invalid",
                       "project entry requires a non-empty checkout path",
                       path=f"{prefix}.checkout" if in_list else "projects")]
    issues: list[ValidationIssue] = []
    allowed = {"checkout", "project_id", "env", "board"} if in_list \
        else {"project_id", "env", "board"}
    for key in sorted(set(entry) - allowed):
        issues.append(_error("project_key_invalid",
                             f"project entry does not support {key!r}",
                             path=f"{prefix}.{key}"))
    if normalize_project_id(entry.get("project_id")) is None:
        issues.append(_error("project_id_required",
                             "project entry requires a positive integer project_id",
                             path=f"{prefix}.project_id"))
    issues.extend(_validate_project_env(entry, prefix=prefix,
                                        connection_labels=connection_labels))
    issues.extend(_validate_project_board(entry.get("board"), prefix=prefix))
    return issues


def _validate_project_env(
    entry: Mapping[str, Any],
    *,
    prefix: str,
    connection_labels: frozenset[str] | set[str],
) -> list[ValidationIssue]:
    env = entry.get("env")
    if not _is_nonempty_str(env):
        # Warning, not error: an untagged legacy entry still resolves under the
        # active env (permissive read), so a not-yet-stamped config keeps
        # working. `yoke status` surfaces the warning; the repair clears it.
        return [_warn("project_env_required",
                      "project entry has no env naming the connection env whose "
                      "universe the project_id belongs to; it resolves only under "
                      "the active env until stamped",
                      path=f"{prefix}.env",
                      hint="Stamp legacy entries with `yoke config stamp-project-env`.")]
    if connection_labels and str(env).strip() not in connection_labels:
        return [_error("project_env_unknown",
                       f"project env {str(env).strip()!r} has no entry in connections "
                       f"(configured: {sorted(connection_labels)})",
                       path=f"{prefix}.env")]
    return []


def _validate_project_board(board: Any, *, prefix: str) -> list[ValidationIssue]:
    if board is None:
        return []
    if not isinstance(board, Mapping):
        return [_error("project_board_invalid",
                       "project board must be an object",
                       path=f"{prefix}.board")]
    issues: list[ValidationIssue] = []
    allowed = {"render_path", "scope"}
    for key in sorted(set(board) - allowed):
        issues.append(_error("project_board_key_invalid",
                             f"project board does not support {key!r}",
                             path=f"{prefix}.board.{key}",
                             hint="Use only render_path and scope. board-art is always .yoke/board-art."))
    for key in allowed:
        if key in board and not _is_nonempty_str(board.get(key)):
            issues.append(_error("project_board_value_invalid",
                                 f"project board {key} must be a non-empty string",
                                 path=f"{prefix}.board.{key}"))
    return issues
