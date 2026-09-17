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
    """Return the paths a RECORDED install is the SOLE author of.

    The sibling :func:`owned_paths` answers for one run's report. This
    answers it for the install already on disk, which is what a later run
    has when it must decide whether a commit it did not make touched only
    installer territory.

    Whole-file ownership is the narrow claim, and only the bundle's own
    generated output earns it: the operator is not invited to edit these
    files, so their whole content is answerable to the install. The two
    co-owned families answer separately, because a caller proving ownership
    must not be handed text that is not the install's —
    :func:`managed_region_paths` for the files carrying a marked block, and
    :func:`shared_paths` for the ones whose entries and lines the install
    merges in beside the operator's own.
    """
    manifest = manifest if isinstance(manifest, Mapping) else {}
    paths: list[str] = []
    for key in ("files", "strategy_files", "git_hook_hashes"):
        section = manifest.get(key)
        if isinstance(section, Mapping):
            paths.extend(str(path) for path in section if path)
    paths.append(MANIFEST_REL)
    return normalized(paths)


def shared_paths(
    manifest: Mapping[str, Any] | None,
    report: Mapping[str, Any] | None = None,
) -> list[str]:
    """Return the co-owned files whose two authors cannot be told apart.

    Hook settings, the ignore files, and the file-line policy config each
    carry the install's entries inside the operator's own document, merged
    with no marker between them. A managed markdown block can be compared
    around because it is delimited; a merged JSON hook subtree and an
    appended ignore line cannot be separated from the operator's without a
    differ per format. So these paths are NAMED rather than claimed: a
    commit touching one is not provably the install's, and publication
    refuses it instead of guessing — which is the conservative answer,
    because the alternative is resetting or publishing an operator edit.

    Contract files are here for a different reason with the same effect:
    they are seeded only when absent and are the project's own from the
    moment they land.
    """
    manifest = manifest if isinstance(manifest, Mapping) else {}
    report = report if isinstance(report, Mapping) else {}
    paths: list[str] = [
        *HOOK_SETTINGS,
        *CURSOR_CONFIG_RELS,
        GITIGNORE_REL,
        YOKE_GITIGNORE_REL,
        RETIRED_EXCEPTIONS_REL,
        PROJECT_CONFIG_REL,
    ]
    for key in ("contract_files", "hook_entries"):
        section = manifest.get(key)
        if isinstance(section, Mapping):
            paths.extend(str(path) for path in section if path)
    paths.extend(_string_list(manifest.get("created_settings_files")))
    for key in (
        "contract_files_written",
        "contract_files_adopted",
        "created_settings_files",
    ):
        paths.extend(_string_list(report.get(key)))
    for mapping_key in ("hooks_added", "hooks_removed"):
        mapping = report.get(mapping_key) or {}
        if isinstance(mapping, dict):
            paths.extend(str(key) for key in mapping if key)
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
    "shared_paths",
]
