"""Detect that the relay's serving source changed and re-exec into it.

A standing relay keeps one Python interpreter alive across every poll, so
the code it serves is the code it was started with. An in-place source
update — a deploy, an editable-install checkout moving forward — would
otherwise be served only after an operator noticed and restarted the
service. Worse, the same update applied underneath a *running* process can
leave it serving half-old modules.

The daemon therefore fingerprints the source it loaded, re-fingerprints
between cycles, and when the two disagree finishes what it is holding and
replaces itself with a fresh interpreter over the new source. Replacing is
never the same as stopping: a relay that stops serving is a machine whose
launches and wakes silently stop landing.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from typing import Iterable, Sequence


# Packages whose modules make up the relay's serving behavior. A change to
# any of them changes what a poll cycle does.
SERVING_PACKAGES: tuple[str, ...] = (
    "yoke_harness",
    "yoke_core",
    "yoke_cli",
    "yoke_contracts",
)


def _package_roots(modules: dict[str, object] | None = None) -> list[Path]:
    """Return the on-disk root of every loaded serving package."""
    loaded = sys.modules if modules is None else modules
    roots: list[Path] = []
    for name in SERVING_PACKAGES:
        module = loaded.get(name)
        origin = getattr(module, "__file__", None)
        if isinstance(origin, str) and origin:
            roots.append(Path(origin).resolve().parent)
    return roots


def _source_files(roots: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        try:
            files.extend(sorted(root.rglob("*.py")))
        except OSError:
            continue
    return files


def source_fingerprint(roots: Sequence[Path] | None = None) -> str:
    """Return a digest over the serving source's paths, sizes, and mtimes.

    Content hashing every module on every cycle would read tens of
    megabytes for a check that almost always says "unchanged", so the
    digest covers the metadata an in-place update moves. An update that
    preserved every size and mtime would be invisible here — and would
    also be invisible to every other tool that reasons about file state.
    """
    digest = hashlib.sha256()
    for path in _source_files(_package_roots() if roots is None else roots):
        try:
            stat = path.stat()
        except OSError:
            continue
        digest.update(str(path).encode("utf-8"))
        digest.update(f"{stat.st_size}:{stat.st_mtime_ns}".encode("utf-8"))
    return digest.hexdigest()


def source_changed(previous: str, roots: Sequence[Path] | None = None) -> bool:
    """Return whether the serving source moved since *previous* was taken."""
    return bool(previous) and source_fingerprint(roots) != previous


def exec_reload(
    argv: Sequence[str] | None = None,
    *,
    executable: str | None = None,
    exec_call=os.execv,
) -> None:
    """Replace this process with a fresh interpreter over the same argv.

    Returns only when the exec fails; the caller then keeps serving on the
    source it already has, which is strictly better than exiting.
    """
    binary = executable or sys.executable
    arguments = list(argv if argv is not None else sys.argv)
    exec_call(binary, [binary, *arguments])


__all__ = [
    "SERVING_PACKAGES",
    "exec_reload",
    "source_changed",
    "source_fingerprint",
]
