"""Ownership checks and native links for one canonical installed skill tree."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from yoke_cli.project_install.files import (
    ProjectInstallError,
    assert_resolved_targets_within,
    sha256_text,
)
from yoke_contracts.project_contract.install_bundle import SKILL_DISCOVERY_LINKS
from yoke_contracts.project_contract.installed_layer import (
    CLAUDE_SKILLS_DEST,
    CODEX_SKILLS_DEST,
    CURSOR_SKILLS_DEST,
)


def validate_links(value: Any) -> dict[str, str]:
    if value != SKILL_DISCOVERY_LINKS:
        raise ProjectInstallError(
            "skill_discovery_contract_unsupported: bundle must name the canonical "
            "Claude discovery link; upgrade the CLI and serving release together"
        )
    return dict(SKILL_DISCOVERY_LINKS)


def preflight(root: Path, prior: dict[str, Any]) -> None:
    """Refuse unowned/edited obsolete copies before any install mutation."""
    hashes = prior.get("files") or {}
    # Probe the native primitive before pruning a baseline-owned tree. No
    # project file is changed by this temporary capability check.
    try:
        with tempfile.TemporaryDirectory(prefix="yoke-skill-link-") as scratch:
            (Path(scratch) / "entry").symlink_to("source", target_is_directory=True)
    except OSError as exc:
        raise _link_refusal() from exc
    for rel in (CLAUDE_SKILLS_DEST, CODEX_SKILLS_DEST, CURSOR_SKILLS_DEST):
        target = root / rel
        assert_resolved_targets_within(root, [rel], context="skill discovery")
        if target.is_symlink():
            if (
                rel in SKILL_DISCOVERY_LINKS
                and os.readlink(target) == SKILL_DISCOVERY_LINKS[rel]
            ):
                continue
            _refuse(rel, "an unowned or unexpected symlink")
        if not target.exists():
            continue
        if not target.is_dir():
            _refuse(rel, "an unexpected non-directory")
        for path in target.rglob("*"):
            if path.is_symlink():
                _refuse(str(path.relative_to(root)), "a symlink inside a legacy copy")
            if path.is_dir():
                continue
            path_rel = path.relative_to(root).as_posix()
            try:
                digest = sha256_text(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError):
                _refuse(path_rel, "an unreadable legacy copy")
            if hashes.get(path_rel) != digest:
                _refuse(path_rel, "a modified copy or missing ownership baseline")


def _refuse(rel: str, detail: str) -> None:
    raise ProjectInstallError(
        f"skill_discovery_ownership_ambiguous: {rel} contains {detail}. "
        "Preserved all files. Compare with the prior install manifest, move "
        "your edits into the canonical .agents/skills/yoke tree, and move the "
        "obsolete discovery entry outside skill directories before refresh. "
        "For a clone, supply the original manifest with --manifest-from on "
        "the source-dev refresh surface; do not infer ownership from equal copies."
    )


def apply(root: Path) -> list[str]:
    """Create the required native entry after baseline-owned copies prune."""
    changed = []
    for rel, destination in SKILL_DISCOVERY_LINKS.items():
        target = root / rel
        if target.is_symlink():
            continue  # preflight already established its exact target
        if target.is_dir():
            # Only empty directories remain after the checked prune pass.
            for directory in sorted(
                target.rglob("*"), key=lambda p: len(p.parts), reverse=True
            ):
                if directory.is_dir():
                    directory.rmdir()
            target.rmdir()
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.symlink_to(destination, target_is_directory=True)
        except OSError as exc:
            raise _link_refusal() from exc
        changed.append(rel)
    return changed


def _link_refusal() -> ProjectInstallError:
    return ProjectInstallError(
        "skill_discovery_link_unavailable: cannot create Claude's native "
        "discovery link. Enable native symlink support (Windows Developer Mode "
        "or administrator permission), then rerun refresh; duplicate skill "
        "copies are unsupported."
    )


def prune_records(root: Path, prior: dict[str, str]) -> dict[str, str]:
    """Stale alias records must never prune through a link into canonical files."""
    linked = [rel + "/" for rel in SKILL_DISCOVERY_LINKS if (root / rel).is_symlink()]
    return {
        rel: digest
        for rel, digest in prior.items()
        if not any(rel.startswith(prefix) for prefix in linked)
    }


def remove(root: Path, records: Any) -> list[str]:
    """Unlink only the exact discovery entries recorded by this installer."""
    if not records:
        return []
    links = validate_links(records)
    removed = []
    for rel, destination in links.items():
        target = root / rel
        assert_resolved_targets_within(root, [rel], context="discovery unlink")
        if target.is_symlink() and os.readlink(target) == destination:
            target.unlink()
            removed.append(rel)
        elif target.exists() or target.is_symlink():
            _refuse(rel, "a changed discovery entry")
    return removed
