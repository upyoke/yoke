"""Filesystem paths, manifest reads, bundle writes, and refresh pruning.

Bundles own whole files; contract files seed project-owned content.
Uninstall removal lives in its own operation module.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from yoke_cli.project_install.line_endings import fold_newlines
from yoke_contracts.cursor_permissions import CURSOR_CONFIG_RELS
from yoke_contracts.project_contract.install_policy import (
    FORBIDDEN_CONTRACT_RELATIVE_PATHS,
)

MANIFEST_SCHEMA = 1
MANIFEST_REL = ".yoke/install-manifest.json"

# Delivery strategy under MODE_KEY: ``copy`` applies a rendered bundle;
# ``source-link`` wires the Yoke source checkout. No key means copy.
MODE_KEY = "mode"
MODE_COPY = "copy"
MODE_SOURCE_LINK = "source-link"
DISCARDED_PRIOR_CONTRACT_RECORDS_KEY = "_discarded_prior_contract_records"
DISCARDED_PRIOR_STRATEGY_RECORDS_KEY = "_discarded_prior_strategy_records"

HOOK_MERGE_TARGETS = (
    ".claude/settings.json",
    ".codex/hooks.json",
    ".cursor/hooks.json",
)


class ProjectInstallError(RuntimeError):
    """Install/refresh/uninstall cannot proceed; message names the repair."""


def resolve_repo_root(repo_root) -> Path:
    """Resolve and validate the target repo root (default: cwd)."""
    import os

    root = Path(repo_root) if repo_root else Path(os.getcwd())
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise ProjectInstallError(f"repo root is not a directory: {root}")
    return root


def sha256_text(content: str) -> str:
    """Digest of managed text, stable under Git line-ending conversion."""
    return hashlib.sha256(fold_newlines(content).encode("utf-8")).hexdigest()


def manifest_path(repo_root: Path) -> Path:
    return repo_root / MANIFEST_REL


def load_manifest(repo_root: Path) -> Dict[str, Any] | None:
    """Return the parsed install manifest, or ``None`` when absent."""
    return load_manifest_path(manifest_path(repo_root), missing_ok=True)


def load_manifest_path(
    path: Path, *, missing_ok: bool = False
) -> Dict[str, Any] | None:
    """Read a manifest from an explicit path for lineage transfer."""
    path = path.expanduser().resolve()
    if not path.is_file():
        if missing_ok:
            return None
        raise ProjectInstallError(f"install manifest does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ProjectInstallError(
            f"install manifest {path} is unreadable ({exc}); repair or delete "
            "it, then rerun `yoke project install`"
        ) from exc
    from yoke_cli.project_install.manifest import sanitize_prior_manifest_records

    sanitized = sanitize_prior_manifest_records(payload, source=str(path))
    validate_manifest(sanitized, source=str(path))
    return sanitized


def write_manifest(repo_root: Path, manifest: Dict[str, Any]) -> Path:
    validate_manifest(manifest, source="new install manifest")
    assert_resolved_targets_within(
        repo_root,
        [MANIFEST_REL],
        context="install manifest write",
    )
    path = manifest_path(repo_root)
    from yoke_cli.project_install.install_recovery import atomic_text, record_manifest

    content = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    record_manifest(repo_root, content)
    atomic_text(path, content)
    return path


def validate_manifest(manifest: Any, *, source: str = "install manifest") -> None:
    """Compatibility export for the split manifest validator."""
    from yoke_cli.project_install.manifest import validate_manifest as validate

    validate(manifest, source=source)


def assert_resolved_targets_within(
    repo_root: Path,
    paths: Iterable[str],
    *,
    context: str,
) -> None:
    """Refuse mutation targets whose existing symlink parents escape root."""
    root = repo_root.expanduser().resolve()
    for rel in paths:
        if not isinstance(rel, str) or not rel:
            raise ProjectInstallError(f"{context} contains an invalid path")
        path = Path(rel)
        if path.is_absolute() or ".." in path.parts:
            raise ProjectInstallError(
                f"{context} names unsafe repo-relative path {rel!r}"
            )
        try:
            resolved = (root / path).resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise ProjectInstallError(
                f"{context} target {rel!r} cannot be resolved safely: {exc}"
            ) from exc
        if resolved != root and root not in resolved.parents:
            raise ProjectInstallError(
                f"{context} target {rel!r} resolves outside repo root "
                f"through a symlink parent ({resolved})"
            )


def assert_file_targets_plannable(
    repo_root: Path,
    paths: Iterable[str],
    *,
    context: str,
) -> None:
    """Reject predictable non-file/parent-shape failures before mutation."""
    selected = list(paths)
    assert_resolved_targets_within(repo_root, selected, context=context)
    root = repo_root.resolve()
    for rel in selected:
        target = root / rel
        if target.exists() and not target.is_file():
            raise ProjectInstallError(
                f"{context} target {rel!r} exists but is not a regular file"
            )
        parent = target.parent
        while parent != root and not parent.exists():
            parent = parent.parent
        if parent.exists() and not parent.is_dir():
            raise ProjectInstallError(
                f"{context} target {rel!r} has a non-directory parent"
            )


def assert_safe_bundle_paths(paths: Iterable[str]) -> None:
    """Admit managed docs/manifests and refuse unsafe or merge-managed paths."""
    managed = ((".yoke", "docs"), (".yoke", "harness"))
    for raw in paths:
        path = Path(raw)
        bad = (
            not raw
            or path.is_absolute()
            or ".." in path.parts
            or raw in HOOK_MERGE_TARGETS + CURSOR_CONFIG_RELS
            or (path.parts[0] == ".yoke" and path.parts[:2] not in managed)
        )
        if bad:
            raise ProjectInstallError(
                f"bundle names an unsafe path {raw!r}: paths must be "
                "repo-relative, must not traverse '..', must not land under "
                ".yoke/ (except .yoke/docs/ and .yoke/harness/), and "
                "merge-managed harness "
                "config flows through its install pass, not a literal file"
            )


def assert_safe_contract_paths(paths: Iterable[str]) -> None:
    """Refuse contract paths outside ``.yoke/`` or naming owned surfaces.

    Contract files are the only bundle entries allowed under ``.yoke/``;
    they must never name the install manifest, generated board views, or
    the runtime/state directories in
    ``project_contract.FORBIDDEN_CONTRACT_RELATIVE_PATHS``.
    """
    forbidden = set(FORBIDDEN_CONTRACT_RELATIVE_PATHS) | {MANIFEST_REL}
    for raw in paths:
        path = Path(raw)
        bad = (
            not raw
            or path.is_absolute()
            or ".." in path.parts
            or path.parts[0] != ".yoke"
            or any(raw == f or raw.startswith(f + "/") for f in forbidden)
        )
        if bad:
            raise ProjectInstallError(
                f"bundle names an unsafe contract path {raw!r}: contract "
                "paths must be repo-relative under .yoke/, must not "
                "traverse '..', and must not name the install manifest, "
                "generated board views, or runtime/state directories"
            )


def apply_contract_files(
    repo_root: Path,
    entries: List[Dict[str, str]],
    old_contract: Dict[str, str],
) -> Tuple[Dict[str, str], List[str], List[str], List[str]]:
    """Seed project contract entries without replacing existing files."""
    from yoke_cli.project_install.contract_files import apply_contract_files as apply

    return apply(repo_root, entries, old_contract)


def reconcile_gitignore(
    repo_root: Path,
    contract_entries: List[Dict[str, str]],
) -> List[str]:
    """Backfill canonical ignore entries into an existing contract file."""
    from yoke_cli.project_install.contract_files import reconcile_gitignore as apply

    return apply(repo_root, contract_entries)


def apply_files(
    repo_root: Path, bundle_files: List[Dict[str, str]]
) -> Tuple[Dict[str, str], List[str]]:
    """Write bundle files idempotently; return (path->sha256, written paths)."""
    assert_resolved_targets_within(
        repo_root,
        (entry["path"] for entry in bundle_files),
        context="bundle file mutation",
    )
    hashes: Dict[str, str] = {}
    written: List[str] = []
    for entry in bundle_files:
        rel, content = entry["path"], entry["content"]
        digest = sha256_text(content)
        hashes[rel] = digest
        target = repo_root / rel
        if target.is_file():
            try:
                current = target.read_bytes().decode("utf-8")
            except (OSError, UnicodeDecodeError):
                current = None
            if current is not None and sha256_text(current) == digest:
                continue
        target.parent.mkdir(parents=True, exist_ok=True)
        from yoke_cli.project_install.install_recovery import atomic_text

        atomic_text(target, content)
        written.append(rel)
    return hashes, written


def prune_files(
    repo_root: Path,
    old_files: Dict[str, str],
    new_paths: Iterable[str],
) -> Tuple[List[str], List[str], List[str]]:
    """Delete old-manifest files absent from the new bundle.

    Returns (pruned, skipped_modified, warnings). Only files whose current
    hash still matches the old manifest hash are deleted; locally modified
    files are preserved with a warning and drop out of Yoke management.
    """
    assert_resolved_targets_within(
        repo_root,
        old_files,
        context="bundle prune",
    )
    keep = set(new_paths)
    pruned: List[str] = []
    skipped: List[str] = []
    warnings: List[str] = []
    for rel in sorted(set(old_files) - keep):
        target = repo_root / rel
        if not target.is_file():
            continue
        try:
            current = target.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            current = None
        if current is None or sha256_text(current) != old_files[rel]:
            skipped.append(rel)
            warnings.append(
                f"{rel} left the bundle but has local modifications; "
                "preserved and no longer Yoke-managed"
            )
            continue
        target.unlink()
        remove_empty_parents(repo_root, rel)
        pruned.append(rel)
    return pruned, skipped, warnings


def remove_empty_parents(repo_root: Path, rel: str) -> None:
    """Remove now-empty parent dirs of ``rel`` up to (excluding) repo root."""
    assert_resolved_targets_within(
        repo_root,
        [rel],
        context="empty parent cleanup",
    )
    parent = (repo_root / rel).parent
    root = repo_root.resolve()
    while parent.resolve() != root and root in parent.resolve().parents:
        try:
            parent.rmdir()
        except OSError:
            return  # not empty (or already gone) — stop walking
        parent = parent.parent


__all__ = [
    "HOOK_MERGE_TARGETS",
    "MANIFEST_REL",
    "MANIFEST_SCHEMA",
    "MODE_COPY",
    "MODE_KEY",
    "MODE_SOURCE_LINK",
    "ProjectInstallError",
    "apply_contract_files",
    "apply_files",
    "assert_file_targets_plannable",
    "assert_resolved_targets_within",
    "assert_safe_bundle_paths",
    "assert_safe_contract_paths",
    "load_manifest",
    "load_manifest_path",
    "manifest_path",
    "prune_files",
    "remove_empty_parents",
    "resolve_repo_root",
    "sha256_text",
    "validate_manifest",
    "write_manifest",
]
