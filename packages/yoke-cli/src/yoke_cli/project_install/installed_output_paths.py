"""Which repository paths an install report claims as its own output.

``project install`` writes bundle files, contract files, managed markdown,
harness hooks and settings, then commits exactly the paths it touched. The
commit and the post-install cleanliness check both need the same answer to
"what did this run write?", so the derivation lives here rather than inside
either caller.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_cli.project_install.files import MANIFEST_REL
from yoke_contracts.cursor_permissions import CURSOR_CONFIG_RELS
from yoke_contracts.project_contract.file_line_policy import PROJECT_CONFIG_REL

GITIGNORE_REL = ".gitignore"
YOKE_GITIGNORE_REL = ".yoke/.gitignore"
RETIRED_EXCEPTIONS_REL = ".yoke/file-line-exceptions"
HOOK_SETTINGS = (
    ".claude/settings.json",
    ".codex/hooks.json",
    ".cursor/hooks.json",
)


def owned_paths(report: Mapping[str, Any] | None) -> list[str]:
    """Return the repo-relative paths the install report owns, in order."""
    report = report if isinstance(report, Mapping) else {}
    paths: list[str] = []
    for key in (
        "files_written",
        "files_pruned",
        "contract_files_written",
        "contract_files_adopted",
        "strategy_files_written",
        "managed_markdown_written",
        "created_settings_files",
    ):
        paths.extend(_string_list(report.get(key)))
    for mapping_key in ("hooks_added", "hooks_removed"):
        mapping = report.get(mapping_key) or {}
        if isinstance(mapping, dict):
            paths.extend(str(key) for key in mapping if key)
    if report.get("gitignore_ignores_backfilled"):
        paths.append(YOKE_GITIGNORE_REL)
    worktrees = report.get("worktrees_ignore") or {}
    if isinstance(worktrees, dict) and (
        worktrees.get("applied") or worktrees.get("status") == "written"
    ):
        paths.append(GITIGNORE_REL)
    if report.get("settings_permissions_actions") or report.get(
        "settings_status_line_actions"
    ):
        paths.append(HOOK_SETTINGS[0])
    if report.get("cursor_permissions_actions"):
        paths.extend(CURSOR_CONFIG_RELS)
    exceptions = report.get("file_line_managed_exceptions") or {}
    if isinstance(exceptions, dict) and exceptions.get("status") == "ok":
        paths.append(PROJECT_CONFIG_REL)
    migration = report.get("file_line_config_migration") or {}
    if isinstance(migration, dict) and migration.get("status") == "ok":
        paths.append(PROJECT_CONFIG_REL)
        paths.append(RETIRED_EXCEPTIONS_REL)
    paths.append(MANIFEST_REL)
    paths.extend(HOOK_SETTINGS)
    return normalized(paths)


def manifest_owned_paths(manifest: Mapping[str, Any] | None) -> list[str]:
    """Return the repo-relative paths a RECORDED install claims as its own.

    The sibling :func:`owned_paths` answers that for one run's report. This
    answers it for the install already on disk, which is what a later run
    has when it must decide whether a commit it did not make touched only
    installer territory. Path-keyed manifest sections contribute their keys;
    list-valued ones contribute their entries.

    Managed-markdown files are deliberately absent: the install owns one
    marked block inside each of them and the operator owns everything
    around it, so naming the whole path here would hand a caller ownership
    of text that is not the install's. :func:`managed_region_paths` answers
    for those, and a caller proving ownership must treat them separately.
    """
    manifest = manifest if isinstance(manifest, Mapping) else {}
    paths: list[str] = []
    for key in (
        "files",
        "contract_files",
        "strategy_files",
        "git_hook_hashes",
        "hook_entries",
    ):
        section = manifest.get(key)
        if isinstance(section, Mapping):
            paths.extend(str(path) for path in section if path)
    paths.extend(_string_list(manifest.get("created_settings_files")))
    paths.append(MANIFEST_REL)
    paths.extend(HOOK_SETTINGS)
    paths.extend(
        (
            GITIGNORE_REL,
            YOKE_GITIGNORE_REL,
            RETIRED_EXCEPTIONS_REL,
            PROJECT_CONFIG_REL,
        )
    )
    paths.extend(CURSOR_CONFIG_RELS)
    return normalized(paths)


def managed_region_paths(
    manifest: Mapping[str, Any] | None,
    report: Mapping[str, Any] | None = None,
) -> list[str]:
    """Return the co-owned files where the install owns only its block.

    Both sides of the same question, in one place: the files a recorded
    install manages and the ones this run wrote. Ownership of these paths is
    region-scoped, never whole-file.
    """
    manifest = manifest if isinstance(manifest, Mapping) else {}
    report = report if isinstance(report, Mapping) else {}
    paths: list[str] = []
    section = manifest.get("managed_markdown")
    if isinstance(section, Mapping):
        paths.extend(str(path) for path in section if path)
    paths.extend(_string_list(report.get("managed_markdown_written")))
    return normalized(paths)


def normalized(paths: list[str]) -> list[str]:
    """De-duplicate repo-relative paths, dropping empties and git internals."""
    ordered: list[str] = []
    seen: set[str] = set()
    for path in paths:
        rel = str(path).replace("\\", "/")
        if rel.startswith("./"):
            rel = rel[2:]
        if not rel or rel.startswith(".git/") or rel in seen:
            continue
        seen.add(rel)
        ordered.append(rel)
    return ordered


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item]


__all__ = [
    "GITIGNORE_REL",
    "managed_region_paths",
    "manifest_owned_paths",
    "HOOK_SETTINGS",
    "RETIRED_EXCEPTIONS_REL",
    "YOKE_GITIGNORE_REL",
    "normalized",
    "owned_paths",
]
