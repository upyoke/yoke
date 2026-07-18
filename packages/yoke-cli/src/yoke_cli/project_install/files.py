"""File/manifest layer for ``yoke install`` / ``refresh`` / ``uninstall``.

Owns the client-side install manifest (``.yoke/install-manifest.json``),
sha256-idempotent file writes, refresh pruning, the seed-if-missing
project-contract pass, and path-safety guards. Pure local filesystem
mechanics — bundle resolution and hook merging live in the sibling
:mod:`runner` / :mod:`hooks` modules.

JSON via stdlib follows the :mod:`machine_config_writer` precedent.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from yoke_contracts.project_contract.install_policy import (
    FORBIDDEN_CONTRACT_RELATIVE_PATHS,
)

MANIFEST_SCHEMA = 1
MANIFEST_REL = ".yoke/install-manifest.json"

# Delivery strategy, recorded in the manifest under MODE_KEY. ``copy``
# applies a rendered bundle (external project repos); ``source-link``
# wires the Yoke source checkout's tracked symlinks + git hooks.
# Manifests without the key are copy manifests (pre-mode state).
MODE_KEY = "mode"
MODE_COPY = "copy"
MODE_SOURCE_LINK = "source-link"

# Hook-merge targets — bundle ``files`` must never name these directly;
# their content flows through the bundle's ``hooks`` subtrees.
HOOK_MERGE_TARGETS = (".claude/settings.json", ".codex/hooks.json")

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
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def manifest_path(repo_root: Path) -> Path:
    return repo_root / MANIFEST_REL


def load_manifest(repo_root: Path) -> Dict[str, Any] | None:
    """Return the parsed install manifest, or ``None`` when absent."""
    return load_manifest_path(manifest_path(repo_root), missing_ok=True)


def load_manifest_path(
    path: Path, *, missing_ok: bool = False,
) -> Dict[str, Any] | None:
    """Read a manifest from an explicit path for lineage transfer."""
    path = path.expanduser().resolve()
    if not path.is_file():
        if missing_ok:
            return None
        raise ProjectInstallError(f"install manifest does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProjectInstallError(
            f"install manifest {path} is unreadable ({exc}); repair or delete "
            "it, then rerun `yoke project install`"
        ) from exc
    validate_manifest(payload, source=str(path))
    return payload


def write_manifest(repo_root: Path, manifest: Dict[str, Any]) -> Path:
    validate_manifest(manifest, source="new install manifest")
    assert_resolved_targets_within(
        repo_root, [MANIFEST_REL], context="install manifest write",
    )
    path = manifest_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def validate_manifest(manifest: Any, *, source: str = "install manifest") -> None:
    """Compatibility export for the split manifest validator."""
    from yoke_cli.project_install.manifest import validate_manifest as validate

    validate(manifest, source=source)


def assert_resolved_targets_within(
    repo_root: Path, paths: Iterable[str], *, context: str,
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
    repo_root: Path, paths: Iterable[str], *, context: str,
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
    """Refuse bundle paths that could escape or corrupt the repo contract."""
    for raw in paths:
        path = Path(raw)
        bad = (
            not raw
            or path.is_absolute()
            or ".." in path.parts
            or raw in HOOK_MERGE_TARGETS
            or path.parts[0] == ".yoke"
        )
        if bad:
            raise ProjectInstallError(
                f"bundle names an unsafe path {raw!r}: paths must be "
                "repo-relative, must not traverse '..', must not land under "
                ".yoke/, and hook config flows through the bundle's hooks "
                "subtrees rather than literal settings files"
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
    """Seed-if-missing pass over contract entries.

    Returns ``(contract_map, written, existing, adopted)``. ``contract_map``
    carries the seeded sha256 for every installer-created file — including
    prior installs' entries whose paths have since left the bundle, so
    uninstall can still remove an untouched seeded file. Files already
    present are reported in ``existing`` and never written.

    An unrecorded existing file that is byte-identical to the current seed
    is *adopted* (recorded as installer-owned): it is indistinguishable
    from the seed, so a later uninstall removing it loses nothing. This
    also re-adopts tracking lost when a manifest rewrite by an older CLI
    dropped the ``contract_files`` key. Pre-existing files whose content
    differs by even a byte are never recorded, so uninstall preserves them.
    """
    assert_resolved_targets_within(
        repo_root,
        [*(entry["path"] for entry in entries), *old_contract],
        context="contract file mutation",
    )
    contract_map = dict(old_contract)
    written: List[str] = []
    existing: List[str] = []
    adopted: List[str] = []
    for entry in entries:
        rel, content = entry["path"], entry["content"]
        target = repo_root / rel
        if target.exists():
            existing.append(rel)
            if rel not in contract_map and target.is_file():
                try:
                    current = target.read_bytes().decode("utf-8")
                except (OSError, UnicodeDecodeError):
                    current = None
                if current == content:
                    contract_map[rel] = sha256_text(content)
                    adopted.append(rel)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        contract_map[rel] = sha256_text(content)
        written.append(rel)
    return contract_map, written, existing, adopted


def _gitignore_entry(
    contract_entries: List[Dict[str, str]],
) -> Dict[str, str] | None:
    """Return the ``.yoke/.gitignore`` contract entry, if the bundle has one."""
    for entry in contract_entries:
        rel = str(entry.get("path", ""))
        if rel.startswith(".yoke/") and Path(rel).name == ".gitignore":
            return entry
    return None


def reconcile_gitignore(
    repo_root: Path, contract_entries: List[Dict[str, str]],
) -> List[str]:
    """Append canonical ``.yoke/.gitignore`` ignore lines missing from an
    already-present file, returning the lines appended.

    :func:`apply_contract_files` is seed-if-missing — it never touches an
    existing ``.yoke/.gitignore``. A project onboarded before an ignore name
    (e.g. ``strategy/``) entered the canonical set would therefore never pick
    it up on refresh, leaving that project's rendered strategy views tracked.
    This reconcile brings every existing file up to the canonical ignore set
    without clobbering its content or operator-added lines. The canonical
    lines come from the bundle's own gitignore entry (single source), so it
    stays correct as the ignore set evolves. No-ops when the file is absent
    (seed-if-missing already wrote the full canonical file) or already complete.
    """
    entry = _gitignore_entry(contract_entries)
    if entry is None:
        return []
    assert_resolved_targets_within(
        repo_root, [str(entry["path"])], context="contract gitignore mutation",
    )
    target = repo_root / str(entry["path"])
    if not target.is_file():
        return []
    canonical = [
        line
        for line in str(entry["content"]).splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    try:
        current = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    present = {line.strip() for line in current.splitlines() if line.strip()}
    missing = [line for line in canonical if line not in present]
    if not missing:
        return []
    if current and not current.endswith("\n"):
        current += "\n"
    target.write_text(current + "\n".join(missing) + "\n", encoding="utf-8")
    return missing


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
        target.write_text(content, encoding="utf-8")
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
        repo_root, old_files, context="bundle prune",
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


def remove_manifest_files(
    repo_root: Path, files: Dict[str, str]
) -> Tuple[List[str], List[str], List[str], List[str]]:
    """Uninstall pass over manifest files.

    Returns (removed, skipped_modified, already_absent, warnings).
    """
    assert_resolved_targets_within(
        repo_root, files, context="manifest-owned file removal",
    )
    removed: List[str] = []
    skipped: List[str] = []
    absent: List[str] = []
    warnings: List[str] = []
    for rel in sorted(files):
        target = repo_root / rel
        if not target.is_file():
            absent.append(rel)
            continue
        try:
            current = target.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            current = None
        if current is None or sha256_text(current) != files[rel]:
            skipped.append(rel)
            warnings.append(
                f"{rel} has local modifications; preserved (delete manually "
                "if unwanted)"
            )
            continue
        target.unlink()
        remove_empty_parents(repo_root, rel)
        removed.append(rel)
    return removed, skipped, absent, warnings


def remove_empty_parents(repo_root: Path, rel: str) -> None:
    """Remove now-empty parent dirs of ``rel`` up to (excluding) repo root."""
    assert_resolved_targets_within(
        repo_root, [rel], context="empty parent cleanup",
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
    "remove_manifest_files",
    "resolve_repo_root",
    "sha256_text",
    "validate_manifest",
    "write_manifest",
]
