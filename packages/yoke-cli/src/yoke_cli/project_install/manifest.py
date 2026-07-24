"""Validation for mutation-bearing project install manifest fields."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

from yoke_cli.project_install.files import (
    DISCARDED_PRIOR_CONTRACT_RECORDS_KEY,
    DISCARDED_PRIOR_STRATEGY_RECORDS_KEY,
    HOOK_MERGE_TARGETS,
    MANIFEST_SCHEMA,
    MODE_COPY,
    MODE_KEY,
    MODE_SOURCE_LINK,
    ProjectInstallError,
    assert_safe_bundle_paths,
)
from yoke_cli.project_install.managed_git_hooks import GIT_HOOK_NAMES
from yoke_contracts.project_contract.install_policy import (
    FORBIDDEN_CONTRACT_RELATIVE_PATHS,
)
from yoke_contracts.project_contract.strategy_docs_paths import (
    slug_from_view_path,
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _path_map(manifest: dict[str, Any], key: str, *, source: str) -> dict[str, str]:
    if key not in manifest:
        return {}
    value = manifest[key]
    if not isinstance(value, dict):
        raise ProjectInstallError(
            f"{source} field {key!r} must be an object of path-to-sha256 entries"
        )
    for raw_path, digest in value.items():
        if not isinstance(raw_path, str) or not raw_path:
            raise ProjectInstallError(
                f"{source} field {key!r} contains a non-string or empty path"
            )
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            raise ProjectInstallError(
                f"{source} field {key!r} path {raw_path!r} must carry a "
                "lowercase sha256 digest"
            )
    return value


def _prior_contract_path_is_safe(raw: str) -> bool:
    forbidden_suffixes = {
        path.removeprefix(".yoke")
        for path in FORBIDDEN_CONTRACT_RELATIVE_PATHS
    } | {"/install-manifest.json"}
    path = Path(raw)
    root = path.parts[0] if path.parts else ""
    return bool(
        raw
        and not path.is_absolute()
        and ".." not in path.parts
        and root == ".yoke"
        and not any(
            raw == root + suffix or raw.startswith(root + suffix + "/")
            for suffix in forbidden_suffixes
        )
    )


def _assert_safe_prior_contract_paths(paths: Iterable[str]) -> None:
    for raw in paths:
        if not _prior_contract_path_is_safe(raw):
            raise ProjectInstallError(
                f"install manifest names an unsafe contract path {raw!r}: "
                "prior contract paths must stay under .yoke/ and must not "
                "name runtime/state files"
            )


def sanitize_prior_contract_records(
    manifest: Any, *, source: str = "install manifest"
) -> Any:
    """Discard inert out-of-policy contract records from a prior manifest.

    The discarded records are returned as internal report metadata. They are
    never considered mutation targets and are omitted from the next manifest
    rewrite. All remaining manifest fields and record digests stay strict.
    """

    if not isinstance(manifest, dict):
        return manifest
    contracts = _path_map(manifest, "contract_files", source=source)
    discarded = sorted(
        raw for raw in contracts if not _prior_contract_path_is_safe(raw)
    )
    sanitized = dict(manifest)
    sanitized.pop(DISCARDED_PRIOR_CONTRACT_RECORDS_KEY, None)
    if not discarded:
        return sanitized
    sanitized["contract_files"] = {
        raw: digest for raw, digest in contracts.items() if raw not in discarded
    }
    sanitized[DISCARDED_PRIOR_CONTRACT_RECORDS_KEY] = discarded
    return sanitized


def _assert_safe_prior_strategy_paths(paths: Iterable[str]) -> None:
    for raw in paths:
        if not _prior_strategy_path_is_safe(raw):
            raise ProjectInstallError(
                f"install manifest names an unsafe strategy path {raw!r}: "
                "prior strategy paths must be canonical .yoke rendered views"
            )


def _prior_strategy_path_is_safe(raw: str) -> bool:
    path = Path(raw)
    return bool(
        raw
        and not path.is_absolute()
        and ".." not in path.parts
        and slug_from_view_path(raw) is not None
    )


def sanitize_prior_strategy_records(
    manifest: Any, *, source: str = "install manifest"
) -> Any:
    """Discard inert noncanonical strategy records from a prior manifest."""

    if not isinstance(manifest, dict):
        return manifest
    strategies = _path_map(manifest, "strategy_files", source=source)
    discarded = sorted(
        raw for raw in strategies if not _prior_strategy_path_is_safe(raw)
    )
    sanitized = dict(manifest)
    sanitized.pop(DISCARDED_PRIOR_STRATEGY_RECORDS_KEY, None)
    if not discarded:
        return sanitized
    sanitized["strategy_files"] = {
        raw: digest for raw, digest in strategies.items() if raw not in discarded
    }
    sanitized[DISCARDED_PRIOR_STRATEGY_RECORDS_KEY] = discarded
    return sanitized


def sanitize_prior_manifest_records(
    manifest: Any, *, source: str = "install manifest"
) -> Any:
    """Sanitize inert legacy records without weakening new-manifest writes."""

    contracts_sanitized = sanitize_prior_contract_records(manifest, source=source)
    return sanitize_prior_strategy_records(contracts_sanitized, source=source)


def _validate_hook_records(records: Any, *, source: str, settings_rel: str) -> None:
    if not isinstance(records, list):
        raise ProjectInstallError(
            f"{source} hook_entries[{settings_rel!r}] must be an array"
        )
    for record in records:
        if not isinstance(record, dict):
            raise ProjectInstallError(
                f"{source} hook_entries[{settings_rel!r}] contains a "
                "non-object record"
            )
        event = record.get("event")
        matcher = record.get("matcher")
        commands = record.get("commands")
        if (
            not isinstance(event, str)
            or not event
            or (matcher is not None and not isinstance(matcher, str))
            or not isinstance(commands, list)
            or not commands
            or not all(isinstance(command, str) and command for command in commands)
        ):
            raise ProjectInstallError(
                f"{source} hook_entries[{settings_rel!r}] contains an invalid "
                "event/matcher/commands record"
            )


def validate_manifest(manifest: Any, *, source: str = "install manifest") -> None:
    """Validate every owned schema-1 field before any mutation."""
    if not isinstance(manifest, dict):
        raise ProjectInstallError(f"{source} must contain a JSON object")
    schema = manifest.get("manifest_schema")
    if schema != MANIFEST_SCHEMA:
        raise ProjectInstallError(
            f"{source} has manifest_schema {schema!r}; this CLI build understands "
            f"{MANIFEST_SCHEMA} — upgrade the CLI (rerun the public installer) "
            "or delete the manifest and reinstall"
        )
    files = _path_map(manifest, "files", source=source)
    contracts = _path_map(manifest, "contract_files", source=source)
    strategies = _path_map(manifest, "strategy_files", source=source)
    git_hook_hashes = _path_map(manifest, "git_hook_hashes", source=source)
    assert_safe_bundle_paths(files)
    _assert_safe_prior_contract_paths(contracts)
    _assert_safe_prior_strategy_paths(strategies)
    allowed_git_hooks = {f".git/hooks/{name}" for name in GIT_HOOK_NAMES}
    if set(git_hook_hashes) - allowed_git_hooks:
        raise ProjectInstallError(
            f"{source} git_hook_hashes names an unknown managed hook path"
        )
    named_git_hooks = manifest.get("git_hooks", [])
    if (
        not isinstance(named_git_hooks, list)
        or not all(name in GIT_HOOK_NAMES for name in named_git_hooks)
    ):
        raise ProjectInstallError(
            f"{source} git_hooks must contain only managed hook names"
        )
    created = manifest.get("created_settings_files", [])
    if (
        not isinstance(created, list)
        or not all(isinstance(path, str) for path in created)
        or any(path not in HOOK_MERGE_TARGETS for path in created)
    ):
        raise ProjectInstallError(
            f"{source} created_settings_files must contain only known hook "
            "settings paths"
        )
    hook_entries = manifest.get("hook_entries", {})
    if not isinstance(hook_entries, dict):
        raise ProjectInstallError(f"{source} hook_entries must be an object")
    for settings_rel, records in hook_entries.items():
        if settings_rel not in HOOK_MERGE_TARGETS:
            raise ProjectInstallError(
                f"{source} hook_entries names unknown settings path {settings_rel!r}"
            )
        _validate_hook_records(records, source=source, settings_rel=settings_rel)
    managed_markdown = manifest.get("managed_markdown", {})
    if not isinstance(managed_markdown, dict):
        raise ProjectInstallError(f"{source} managed_markdown must be an object")
    for rel, record in managed_markdown.items():
        if not isinstance(rel, str) or not rel or not isinstance(record, dict):
            raise ProjectInstallError(
                f"{source} managed_markdown contains an invalid entry"
            )
    settings_permissions = manifest.get("settings_permissions", {})
    if not isinstance(settings_permissions, dict):
        raise ProjectInstallError(
            f"{source} settings_permissions must be an object"
        )
    mode = manifest.get(MODE_KEY, MODE_COPY)
    if mode not in (MODE_COPY, MODE_SOURCE_LINK):
        raise ProjectInstallError(f"{source} has unknown mode {mode!r}")
    if "yoke_version" in manifest and (
        not isinstance(manifest["yoke_version"], str) or not manifest["yoke_version"]
    ):
        raise ProjectInstallError(f"{source} yoke_version must be a non-empty string")
    if "project_id" in manifest and (
        isinstance(manifest["project_id"], bool)
        or not isinstance(manifest["project_id"], int)
        or manifest["project_id"] <= 0
    ):
        raise ProjectInstallError(f"{source} project_id must be a positive integer")
    if "project_slug" in manifest and (
        not isinstance(manifest["project_slug"], str) or not manifest["project_slug"]
    ):
        raise ProjectInstallError(f"{source} project_slug must be a non-empty string")
    for key in ("worktrees_ignore_added", "worktrees_ignore_created_file"):
        if key in manifest and not isinstance(manifest[key], bool):
            raise ProjectInstallError(f"{source} {key} must be a boolean")


__all__ = [
    "sanitize_prior_contract_records",
    "sanitize_prior_manifest_records",
    "sanitize_prior_strategy_records",
    "validate_manifest",
]
