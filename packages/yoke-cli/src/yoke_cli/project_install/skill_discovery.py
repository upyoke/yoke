"""Local native discovery entries for one canonical installed skill tree.

Claude finds the Yoke skill at ``.claude/skills/yoke``. Each checkout gets
its own entry onto ``.agents/skills/yoke`` through
:func:`yoke_contracts.platform_links.link`: a symlink, a junction where
Windows refuses symlinks, or a copy as the last resort. The entry is local
machine state. The installer's root ``.gitignore`` entry keeps it out of
Git, and the next install commit untracks a link that older installs
committed.

An entry is the installer's own when it is a link resolving to the skill
tree, Git's placeholder file for a committed link checked out without
symlink support, or a directory this install recorded (its copy). Anything
else is the operator's, and install refuses rather than replace it.
"""

from __future__ import annotations

import os
from pathlib import Path
import stat
from typing import Any, Mapping

from yoke_cli.config import project_worktrees_ignore
from yoke_cli.project_install.files import (
    ProjectInstallError,
    assert_resolved_targets_within,
    remove_empty_parents,
)
from yoke_contracts.platform_fs import remove_tree
from yoke_contracts.platform_links import link
from yoke_contracts.project_contract.install_bundle import SKILL_DISCOVERY_LINKS

MISSING = "missing"
LINKED = "linked"
PLACEHOLDER = "placeholder"
COPIED = "copied"
FOREIGN = "foreign"


def ignore_entry(rel: str) -> str:
    """Root ``.gitignore`` line that keeps the local entry *rel* out of Git."""
    return "/" + rel


def ignore(root: Path) -> list[str]:
    """Add the root ``.gitignore`` lines for every entry; return lines written."""
    return [
        ignore_entry(rel)
        for rel in SKILL_DISCOVERY_LINKS
        if project_worktrees_ignore.add_entry(root, ignore_entry(rel))
    ]


def validate_links(value: Any) -> dict[str, str]:
    if value != SKILL_DISCOVERY_LINKS:
        raise ProjectInstallError(
            "skill_discovery_contract_unsupported: bundle must name the canonical "
            "Claude discovery link; upgrade the CLI and serving release together"
        )
    return dict(SKILL_DISCOVERY_LINKS)


def entry_state(root: Path, rel: str, records: Mapping[str, str] | None = None) -> str:
    """Classify the discovery entry at *rel* as installer-owned or foreign."""
    target = root / rel
    destination = SKILL_DISCOVERY_LINKS[rel]
    try:
        info = target.lstat()
    except FileNotFoundError:
        return MISSING
    expected = (target.parent / destination).resolve()
    if is_link_entry(info):
        return LINKED if target.resolve() == expected else FOREIGN
    if stat.S_ISREG(info.st_mode):
        try:
            text = target.read_bytes().decode("utf-8").strip()
        except (OSError, UnicodeDecodeError):
            return FOREIGN
        return PLACEHOLDER if text == destination else FOREIGN
    if stat.S_ISDIR(info.st_mode) and rel in (records or {}):
        return COPIED
    return FOREIGN


def is_link_entry(info: os.stat_result) -> bool:
    """A symlink, or a Windows junction or other reparse point."""
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & reparse
    )


def preflight(root: Path, records: Mapping[str, str] | None = None) -> None:
    """Refuse a foreign discovery entry before any project mutation."""
    for rel in SKILL_DISCOVERY_LINKS:
        assert_resolved_targets_within(root, [rel], context="skill discovery")
        if entry_state(root, rel, records) == FOREIGN:
            _refuse(rel, "an unexpected discovery entry")


def apply(root: Path, records: Mapping[str, str] | None = None) -> list[str]:
    """Create or refresh each local entry after preflight accepted it."""
    changed = []
    for rel, destination in SKILL_DISCOVERY_LINKS.items():
        state = entry_state(root, rel, records)
        if state == LINKED:
            continue
        if state == FOREIGN:
            _refuse(rel, "an unexpected discovery entry")
        target = root / rel
        source = (target.parent / destination).resolve()
        if not source.is_dir():
            raise ProjectInstallError(
                f"skill_discovery_target_missing: {rel} points at "
                f"{destination}, which is not in this checkout. Rerun yoke "
                "project refresh so the bundle restores the skill tree."
            )
        if state != MISSING:
            _remove_entry(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            link(source, target)
        except OSError as exc:
            raise ProjectInstallError(
                f"skill_discovery_link_unavailable: cannot create {rel} ({exc}). "
                "Enable Windows Developer Mode, or allow the checkout folder to "
                "hold junctions or copies, then rerun yoke project refresh."
            ) from exc
        changed.append(rel)
    return changed


def remove(root: Path, records: Any) -> list[str]:
    """Remove only the discovery entries this installer recorded."""
    if not records:
        return []
    links = validate_links(records)
    removed = []
    for rel in links:
        assert_resolved_targets_within(root, [rel], context="discovery unlink")
        state = entry_state(root, rel, links)
        if state == MISSING:
            continue
        if state == FOREIGN:
            _refuse(rel, "a changed discovery entry")
        _remove_entry(root / rel)
        remove_empty_parents(root, rel)
        removed.append(rel)
    return removed


def unignore(root: Path, records: Any) -> list[str]:
    """Drop the root ``.gitignore`` lines of the recorded entries."""
    if not records:
        return []
    return [
        ignore_entry(rel)
        for rel in validate_links(records)
        if project_worktrees_ignore.remove_entry(root, ignore_entry(rel))["removed"]
    ]


def _remove_entry(target: Path) -> None:
    """Remove a link, junction, placeholder or recorded copy without following it."""
    if stat.S_ISREG(target.lstat().st_mode):
        target.unlink()
    else:
        remove_tree(target)


def _refuse(rel: str, detail: str) -> None:
    raise ProjectInstallError(
        f"skill_discovery_entry_conflict: {rel} contains {detail}. "
        "Preserve its contents outside the discovery path, then rerun refresh."
    )


__all__ = [
    "SKILL_DISCOVERY_LINKS",
    "apply",
    "entry_state",
    "ignore",
    "ignore_entry",
    "is_link_entry",
    "preflight",
    "remove",
    "unignore",
    "validate_links",
]
