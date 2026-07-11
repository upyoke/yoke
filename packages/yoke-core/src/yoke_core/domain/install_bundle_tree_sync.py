"""Materialize + drift-check the packaged install-bundle source tree.

``yoke_core.install_bundle_tree`` is a committed, byte-exact snapshot of the
repo-root source dirs the install bundle serves — the Yoke skill tree, the
rendered Claude and Codex agent adapters, and the shared Claude session rules
(:data:`install_bundle.INSTALL_BUNDLE_SOURCE_DIRS`). setuptools cannot ship
files from outside the ``yoke_core`` package as package-data, so the wheel
carries this in-package copy; :func:`install_bundle.server_tree_root` falls
back to it via ``importlib.resources`` whenever the ``runtime`` source package
is not importable (product-wheel mode).

The snapshot is DERIVED, not authored. It has no automated regenerator prior to
this module: an adapter/skill/rules edit that skipped the hand-copy silently
drifted the shipped wheel from source, caught only by a buried pytest. This
module makes the snapshot machine-maintained:

* :func:`sync` regenerates it from the source dirs, byte-for-byte — the
  canonical repair, replacing manual file surgery.
* :func:`detect_drift` reports any divergence and backs both
  ``HC-install-bundle-drift`` and the ``test_install_bundle`` invariant, so
  drift is caught by ``/yoke doctor`` and CI before merge.

Enumeration follows symlinks and materializes them as regular files (the
``references/`` adapter tree symlinks a canonical body that lives outside the
snapshot), so the packaged copy is self-contained and byte-identical to what a
reader sees through the source symlink.

Writes flow through the same ``workspace_authority`` guard the substrate
renderer uses: authorized under the calling session's worktree work-claim, a
no-op for operator/CI contexts with no session, and always allowed for the
free-path temp roots the tests drive.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from yoke_contracts.project_contract.install_manifest import (
    PACKAGED_INSTALL_BUNDLE_TREE_REL,
)
from yoke_core.domain.install_bundle import INSTALL_BUNDLE_SOURCE_DIRS
from yoke_core.domain.workspace_authority import (
    assert_target_under_session_work_authority,
)


# The packaged snapshot's path relative to the repo root. Mirrors the
# pyproject ``[tool.setuptools.package-data] "yoke_core.install_bundle_tree"``
# location so the tracked tree and the wheel package-data resolve one place.
PACKAGED_TREE_REL = Path(PACKAGED_INSTALL_BUNDLE_TREE_REL)


class InstallBundleTreeError(RuntimeError):
    """The packaged snapshot cannot be materialized; message names the repair."""


def _relative_files(root: Path) -> List[str]:
    """POSIX-relative paths of every file under ``root`` (symlinks followed).

    Matches the enumeration the drift invariant and ``build_bundle`` use:
    ``rglob('*')`` + ``is_file()`` dereferences symlinks, so a symlinked source
    file is enumerated (and later materialized) as a regular file.
    """
    if not root.is_dir():
        return []
    return sorted(
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file()
    )


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
    return drift


def sync(*, target_root: Path, dry_run: bool = False) -> Dict[str, List[str]]:
    """Regenerate the packaged snapshot from the source dirs, byte-for-byte.

    Removes packaged files with no source counterpart, writes changed/new files
    atomically, and leaves already-matching files untouched. Returns
    ``{"written": [...], "removed": [...]}`` of ``<source-dir>/<rel>`` labels.
    Raises :class:`InstallBundleTreeError` when a declared source dir is absent.
    """
    repo = Path(target_root)
    packaged = repo / PACKAGED_TREE_REL
    written: List[str] = []
    removed: List[str] = []
    for rel in INSTALL_BUNDLE_SOURCE_DIRS:
        source = repo / rel
        if not source.is_dir():
            raise InstallBundleTreeError(
                f"install-bundle source dir is missing: {source}"
            )
        packed = packaged / rel
        source_files = _relative_files(source)
        source_set = set(source_files)
        for extra in _relative_files(packed):
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
        "--dry-run", action="store_true",
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
            "Repair: python3 -m yoke_core.domain.install_bundle_tree_sync sync"
        )
        return 1

    report = sync(target_root=root, dry_run=args.dry_run)
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
    "PACKAGED_TREE_REL",
    "InstallBundleTreeError",
    "detect_drift",
    "run_cli",
    "sync",
]


if __name__ == "__main__":
    raise SystemExit(run_cli())
