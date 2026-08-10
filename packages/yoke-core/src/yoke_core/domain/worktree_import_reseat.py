"""Keep a running process importable after its source directory is removed.

A merge finishes by deleting the lane worktree, and the process running that
merge may have resolved its own packages out of that lane. Python caches a
package's ``__path__`` at first import and never re-derives it, so every lazy
submodule import issued after the removal searches directories that no longer
exist and raises ``ImportError`` — a merge that already landed then exits
non-zero on its way out, stranding the item mid-close-out.

Reseating rewrites those cached entries onto the surviving checkout before the
directory goes away, so the imports the close-out still owes resolve against
the same code from a tree that will still be there. It is deliberately blind to
package names: whatever the process happens to have loaded out of the doomed
directory is what needs repointing.

Rationale and rejected alternatives: ``docs/archive/decisions/
merge-close-out-completion.md``.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _resolved(value: Path | str) -> Path | None:
    try:
        return Path(value).resolve()
    except (OSError, ValueError):
        return None


def _reseat_entries(
    entries: list[str], doomed: Path, surviving: Path,
) -> tuple[list[str], bool]:
    """Repoint the entries that live under ``doomed``; report whether any did."""
    reseated: list[str] = []
    changed = False
    for entry in entries:
        resolved = _resolved(entry)
        if resolved is None:
            reseated.append(entry)
            continue
        try:
            relative = resolved.relative_to(doomed)
        except ValueError:
            reseated.append(entry)
            continue
        destination = surviving / relative
        # A destination that does not exist would make imports fail in a new
        # way rather than the old one; leave those entries as they are.
        if not destination.is_dir():
            reseated.append(entry)
            continue
        replacement = str(destination)
        reseated.append(replacement)
        changed = changed or replacement != entry
    return reseated, changed


def reseat_loaded_packages(
    *, doomed_root: Path | str, surviving_root: Path | str,
) -> list[str]:
    """Repoint every loaded package that imports out of ``doomed_root``.

    Returns the qualified names that were reseated, which is what tests and
    diagnostics read; production callers treat this as a side effect.
    """
    doomed = _resolved(doomed_root)
    surviving = _resolved(surviving_root)
    if doomed is None or surviving is None or doomed == surviving:
        return []
    reseated: list[str] = []
    for name, module in list(sys.modules.items()):
        paths = getattr(module, "__path__", None)
        if not paths:
            continue
        try:
            entries = [str(entry) for entry in paths]
        except TypeError:
            continue
        replacements, changed = _reseat_entries(entries, doomed, surviving)
        if not changed:
            continue
        try:
            module.__path__ = replacements
        except (AttributeError, TypeError):
            continue
        reseated.append(name)
    return reseated


def reseat_off_launch_directory(
    surviving_root: Path | str, *, anchor_package: str = "runtime",
) -> list[str]:
    """Reseat packages loaded from wherever ``anchor_package`` was imported.

    The launch directory is not passed in by callers that only know where they
    want to end up: it is read back from the anchor package's own cached path,
    which is the directory the process actually imported from.
    """
    module = sys.modules.get(anchor_package)
    paths = getattr(module, "__path__", None) if module is not None else None
    if not paths:
        return []
    try:
        launched_from = _resolved(list(paths)[0])
    except (IndexError, TypeError):
        return []
    if launched_from is None:
        return []
    return reseat_loaded_packages(
        doomed_root=launched_from.parent, surviving_root=surviving_root,
    )


__all__ = ["reseat_loaded_packages", "reseat_off_launch_directory"]
