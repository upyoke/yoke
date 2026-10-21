"""Compare touched paths with declared file and directory coverage."""

from __future__ import annotations

from typing import Iterable, Sequence


def files_outside_coverage(
    touched_paths: Iterable[str],
    declared_paths: Sequence[str],
    declared_target_kinds: Sequence[tuple[str, str]] = (),
) -> list[str]:
    """Return touched paths not covered by *declared_paths*.

    A touched path is covered when it matches a declared path exactly OR
    sits inside a declared directory prefix (declared paths ending with
    ``/`` are treated as directory-prefix matchers). Order is preserved
    from the input.
    """
    kind_by_path = dict(declared_target_kinds)
    declared_files = {
        p for p in declared_paths if p and kind_by_path.get(p, "file") != "directory"
    }
    declared_dirs = [
        p.rstrip("/") + "/"
        for p in declared_paths
        if p
        and (
            kind_by_path.get(p) == "directory"
            or (not declared_target_kinds and p.endswith("/"))
        )
    ]
    out: list[str] = []
    for path in touched_paths:
        if path in declared_files:
            continue
        if any(path.startswith(prefix) for prefix in declared_dirs):
            continue
        out.append(path)
    return out


__all__ = ["files_outside_coverage"]
