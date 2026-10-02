"""Materialize + drift-check the packaged install-bundle source tree.

``yoke_core.install_bundle_tree`` is a committed snapshot of the repo-root
sources served through ``server_tree_root()`` — byte-exact for source dirs and
limited to the managed, project-agnostic region of the root doctrine files.
The wheel carries this derived copy because setuptools cannot package the
repo-root sources directly. Sync is restricted to Yoke source checkouts and
validates required sources before writing; installed projects never run it.
Enumeration materializes source symlinks as regular files, and writes use the
substrate renderer's ``workspace_authority`` guard. Drift checking backs
``HC-install-bundle-drift`` and CI.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from yoke_contracts.install_binding import is_yoke_source_checkout
from yoke_contracts.project_contract.install_manifest import (
    PACKAGED_INSTALL_BUNDLE_TREE_REL,
)
from yoke_contracts.project_contract.managed_block import MANAGED_BLOCK_END
from yoke_core.domain.install_bundle import (
    DOCS_DEST,
    INSTALL_BUNDLE_SOURCE_DIRS,
    is_bundle_junk_path,
)
from yoke_core.domain.install_bundle_docs_mirror import (
    docs_dest_drift,
    mirror_docs_dest,
    prune_empty_dirs,
)
from yoke_core.domain.install_bundle_managed import INSTALL_BUNDLE_SOURCE_FILES
from yoke_core.domain.workspace_authority import (
    assert_target_under_session_work_authority,
)


# The packaged snapshot's path relative to the repo root. Mirrors the
# pyproject ``[tool.setuptools.package-data] "yoke_core.install_bundle_tree"``
# location so the tracked tree and the wheel package-data resolve one place.
PACKAGED_TREE_REL = Path(PACKAGED_INSTALL_BUNDLE_TREE_REL)

# Snapshot files that legitimately exist outside every declared source dir:
# the marker that makes ``yoke_core.install_bundle_tree`` an importable
# package. Everything else outside the declared subtrees is stray.
PACKAGED_TREE_ALLOWED_EXTRAS = ("__init__.py",)


class InstallBundleTreeError(RuntimeError):
    """The packaged snapshot cannot be materialized; message names the repair."""


def _project_agnostic_source_file_bytes(source: Path) -> bytes:
    """Return the root doctrine prefix that is safe to ship to every project."""
    data = source.read_bytes()
    marker = MANAGED_BLOCK_END.encode("utf-8")
    end = data.find(marker)
    if end < 0:
        raise InstallBundleTreeError(
            f"install-bundle root source lacks managed-block boundary: {source}"
        )
    return data[: end + len(marker)] + b"\n"


def _relative_files(root: Path) -> List[str]:
    """POSIX-relative paths of every file under ``root`` (symlinks followed).

    Matches the enumeration the drift invariant and ``build_bundle`` use:
    ``rglob('*')`` + ``is_file()`` dereferences symlinks, so a symlinked source
    file is enumerated (and later materialized) as a regular file. Cache junk
    (``is_bundle_junk_path``) is excluded so bytecode compiled next to
    importable package sources never enters the mirror comparison.
    """
    if not root.is_dir():
        return []
    return sorted(
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and not is_bundle_junk_path(p)
    )


def _relative_files_raw(root: Path) -> List[str]:
    """Like :func:`_relative_files` but junk-inclusive.

    The sync removal pass enumerates the packaged side with this so junk that
    somehow landed in the snapshot is deleted rather than becoming invisible.
    """
    if not root.is_dir():
        return []
    return sorted(
        p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()
    )


def _stray_packaged_files(packaged: Path) -> List[str]:
    """Packaged files outside every declared source-dir subtree.

    The per-dir comparisons only see files under declared prefixes, so a
    file parked elsewhere in the snapshot would otherwise ship in the wheel
    unnoticed.
    """
    prefixes = tuple(f"{rel}/" for rel in INSTALL_BUNDLE_SOURCE_DIRS)
    allowed = set(PACKAGED_TREE_ALLOWED_EXTRAS) | set(INSTALL_BUNDLE_SOURCE_FILES)
    return [
        rel
        for rel in _relative_files(packaged)
        if not rel.startswith(prefixes) and rel not in allowed
    ]


def detect_drift(*, target_root: Path) -> List[str]:
    """Return human-readable descriptions of snapshot-vs-source divergence.

    Empty list means the packaged tree byte-matches the source dirs. Never
    writes — safe for the read-only Doctor check to call in any context.
    """
    repo = Path(target_root)
    packaged = repo / PACKAGED_TREE_REL
    drift: List[str] = []
    for rel in INSTALL_BUNDLE_SOURCE_DIRS:
        source = repo / rel
        packed = packaged / rel
        if not source.is_dir():
            drift.append(f"missing source dir: {rel}")
            continue
        source_set = set(_relative_files(source))
        packed_set = set(_relative_files(packed))
        for extra in sorted(packed_set - source_set):
            drift.append(f"stale packaged file (no source): {rel}/{extra}")
        for missing in sorted(source_set - packed_set):
            drift.append(f"missing packaged file: {rel}/{missing}")
        for name in sorted(source_set & packed_set):
            if (packed / name).read_bytes() != (source / name).read_bytes():
                drift.append(f"content drift: {rel}/{name}")
    for rel in INSTALL_BUNDLE_SOURCE_FILES:
        source_file = repo / rel
        packed_file = packaged / rel
        if not source_file.is_file():
            drift.append(f"missing source file: {rel}")
            continue
        if not packed_file.is_file():
            drift.append(f"missing packaged file: {rel}")
            continue
        expected = _project_agnostic_source_file_bytes(source_file)
        if packed_file.read_bytes() != expected:
            drift.append(f"content drift: {rel}")
    for stray in _stray_packaged_files(packaged):
        drift.append(f"stray packaged file (outside declared source dirs): {stray}")
    drift.extend(docs_dest_drift(repo=repo, relative_files=_relative_files))
    return drift


def sync(*, target_root: Path, dry_run: bool = False) -> Dict[str, List[str]]:
    """Regenerate the packaged snapshot from the source dirs, byte-for-byte.

    Removes packaged files with no source counterpart, writes changed/new files
    atomically, and leaves already-matching files untouched. Returns
    ``{"written": [...], "removed": [...]}`` of ``<source-dir>/<rel>`` labels.
    Raises :class:`InstallBundleTreeError` when a declared source dir is absent.
    """
    repo = Path(target_root)
    if not is_yoke_source_checkout(repo):
        raise InstallBundleTreeError(
            f"install_bundle_target_not_yoke_source: {repo}. "
            "Run sync only with --target-root pointing to a Yoke source checkout; "
            "refresh installed project files with yoke project install."
        )
    for rel in INSTALL_BUNDLE_SOURCE_DIRS:
        if not (repo / rel).is_dir():
            raise InstallBundleTreeError(
                f"install-bundle source dir is missing: {repo / rel}"
            )
    for rel in INSTALL_BUNDLE_SOURCE_FILES:
        if not (repo / rel).is_file():
            raise InstallBundleTreeError(
                f"install-bundle source file is missing: {repo / rel}"
            )
        _project_agnostic_source_file_bytes(repo / rel)
    packaged = repo / PACKAGED_TREE_REL
    written: List[str] = []
    removed: List[str] = []
    for rel in INSTALL_BUNDLE_SOURCE_DIRS:
        source = repo / rel
        packed = packaged / rel
        source_files = _relative_files(source)
        source_set = set(source_files)
        for extra in _relative_files_raw(packed):
            if extra in source_set:
                continue
            removed.append(f"{rel}/{extra}")
            if not dry_run:
                target = packed / extra
                assert_target_under_session_work_authority(target)
                target.unlink()
        for name in source_files:
            data = (source / name).read_bytes()
            dst = packed / name
            if dst.is_file() and dst.read_bytes() == data:
                continue
            written.append(f"{rel}/{name}")
            if not dry_run:
                assert_target_under_session_work_authority(dst)
                dst.parent.mkdir(parents=True, exist_ok=True)
                tmp = dst.with_suffix(dst.suffix + ".tmp")
                tmp.write_bytes(data)
                os.replace(str(tmp), str(dst))
    for rel in INSTALL_BUNDLE_SOURCE_FILES:
        source_file = repo / rel
        data = _project_agnostic_source_file_bytes(source_file)
        dst = packaged / rel
        if dst.is_file() and dst.read_bytes() == data:
            continue
        written.append(rel)
        if not dry_run:
            assert_target_under_session_work_authority(dst)
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_suffix(dst.suffix + ".tmp")
            tmp.write_bytes(data)
            os.replace(str(tmp), str(dst))
    for stray in _stray_packaged_files(packaged):
        removed.append(stray)
        if not dry_run:
            target = packaged / stray
            assert_target_under_session_work_authority(target)
            target.unlink()
    # Remove the retired packaged docs tree (``.yoke/docs`` under the
    # snapshot) if it still exists after the source moved to ``docs/public``.
    legacy_packaged_docs = packaged / ".yoke" / "docs"
    if legacy_packaged_docs.exists():
        for extra in _relative_files_raw(legacy_packaged_docs):
            removed.append(f".yoke/docs/{extra}")
            if not dry_run:
                target = legacy_packaged_docs / extra
                assert_target_under_session_work_authority(target)
                target.unlink()
    mirror = mirror_docs_dest(
        repo=repo,
        dry_run=dry_run,
        relative_files=_relative_files,
        relative_files_raw=_relative_files_raw,
        error_cls=InstallBundleTreeError,
    )
    written.extend(mirror["written"])
    removed.extend(mirror["removed"])
    prune_empty_dirs(
        bases=[repo / DOCS_DEST, packaged / ".yoke" / "docs", packaged / ".yoke"],
        dry_run=dry_run,
    )
    return {"written": written, "removed": removed}


def _resolve_cli_target_root(arg_value: Optional[str]) -> Path:
    """CLI-only target_root resolution (arg / env / repo-root fallback).

    Reuses the substrate renderer's resolver so ``--target-root``,
    ``$YOKE_RENDER_TARGET_ROOT``, and the linked-worktree ambiguity guard
    behave identically to ``agents render``.
    """
    from yoke_core.domain.agents_render_workspace import (
        resolve_target_root_for_cli,
    )

    return resolve_target_root_for_cli(arg_value)


def run_cli(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.domain.install_bundle_tree_sync",
        description=(
            "Materialize or drift-check the packaged install-bundle tree "
            "(yoke_core.install_bundle_tree) against its repo-root source dirs."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p_sync = sub.add_parser(
        "sync", help="Regenerate the snapshot from the source dirs."
    )
    p_sync.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing.",
    )
    p_sync.add_argument("--target-root", default=None)
    p_check = sub.add_parser(
        "check", help="Report drift; exit 1 when the snapshot diverges."
    )
    p_check.add_argument("--target-root", default=None)
    args = parser.parse_args(argv)
    root = _resolve_cli_target_root(args.target_root)

    if args.command == "check":
        drift = detect_drift(target_root=root)
        if not drift:
            print("install-bundle tree: in sync")
            return 0
        print("install-bundle tree DRIFT:")
        for entry in drift:
            print(f"  - {entry}")
        print(
            "Repair: yoke dev run -- python3 -m "
            "yoke_core.domain.install_bundle_tree_sync sync"
        )
        return 1

    try:
        report = sync(target_root=root, dry_run=args.dry_run)
    except InstallBundleTreeError as exc:
        print(str(exc))
        return 1
    verb = "would-write" if args.dry_run else "wrote"
    verb_rm = "would-remove" if args.dry_run else "removed"
    if not report["written"] and not report["removed"]:
        print("install-bundle tree: already in sync")
        return 0
    for name in report["written"]:
        print(f"  {verb}: {name}")
    for name in report["removed"]:
        print(f"  {verb_rm}: {name}")
    return 0


__all__ = [
    "INSTALL_BUNDLE_SOURCE_DIRS",
    "INSTALL_BUNDLE_SOURCE_FILES",
    "PACKAGED_TREE_REL",
    "InstallBundleTreeError",
    "detect_drift",
    "run_cli",
    "sync",
]


if __name__ == "__main__":
    raise SystemExit(run_cli())
