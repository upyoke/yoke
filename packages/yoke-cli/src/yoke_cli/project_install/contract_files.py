"""Seed and reconcile project contract files."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

from yoke_cli.project_install.files import (
    assert_resolved_targets_within,
    sha256_text,
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
    repo_root: Path,
    contract_entries: List[Dict[str, str]],
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
        repo_root,
        [str(entry["path"])],
        context="contract gitignore mutation",
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


__all__ = ["apply_contract_files", "reconcile_gitignore"]
