"""Project-relative path → canonical ``path_targets.id`` resolution.

Sole sanctioned helper for the path-claim on-ramp surfaces (register,
amend, boundary check) to convert operator-supplied project-relative
POSIX path strings into the canonical ``path_targets.id`` values that
the path-claim API consumes.

Two failure modes share one class so callers surface a single rejection
surface to the operator:

* ``UnknownPathTargets`` — at least one path is not present in the
  Canonical Path Registry. Surfaces the offending paths verbatim so
  the operator's first move is either ``yoke project snapshot sync``
  to refresh the registry or to fix the path string.
* ``EmptyPathSet`` — the operator passed no paths. The caller cannot
  default-fill, because a claim with empty coverage is a no-op the API
  would reject anyway.

The helper is intentionally project-scoped: ``path_targets`` rows are
``(project_id, path_string)`` keyed, so callers must resolve the item's
project before delegating here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, List, Optional, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.path_project_relative import invalid_project_relative_paths
from yoke_core.domain.path_registry import (
    KIND_DIRECTORY,
    KIND_FILE,
    target_at,
)
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.path_claims_symlink_expansion import (
    SYMLINK_CANONICALIZED,
    SYMLINK_DANGLING_TARGET,
    SYMLINK_EXTERNAL_TARGET,
    SymlinkDecision,
    expand_symlinks_from_snapshot_facts,
    expand_symlinks_to_canonical,
    normalize_path_list,
)


from yoke_core.domain.path_targets_states import (
    OBSERVED as _OBSERVED,
    TENTATIVE as _TENTATIVE,
)


class PathResolveError(Exception):
    """Base class for project-relative path resolution failures."""


class EmptyPathSet(PathResolveError):
    """The caller passed no paths."""


class UnknownPathTargets(PathResolveError):
    """At least one path has no row in the Canonical Path Registry.

    The exception message names every unknown path so the operator can
    paste them into a snapshot refresh or diff against the working
    tree without having to re-run the command to discover the rest.
    """

    def __init__(self, project_id: int, missing: Sequence[str]) -> None:
        self.project_id = project_id
        self.missing = list(missing)
        super().__init__(
            f"path target(s) not in registry for project {project_id!r}: "
            f"{', '.join(self.missing)}. Likely causes: (a) the file has not "
            "been committed to the integration target yet — re-run with "
            "`--allow-planned` to claim a future path; (b) the snapshot is "
            "stale — refresh via "
            "`yoke project snapshot sync`; "
            "(c) the path is mistyped — verify the spelling against the file tree."
        )


class NonProjectRelativePaths(PathResolveError):
    """At least one path is absolute or escapes the project tree."""

    def __init__(self, paths: Sequence[str]) -> None:
        self.paths = list(paths)
        super().__init__(
            "path claim targets must be project-relative repo paths; "
            f"outside-repo paths are not claimable: {', '.join(self.paths)}"
        )


def _normalize_paths(raw_paths: Iterable[str]) -> List[str]:
    """Strip whitespace, drop empties, preserve operator order, dedupe.

    Order is preserved so the caller's reported ``target_ids`` match the
    operator's typing order in the rare diagnostic case where the caller
    surfaces them — the path-claim API itself is order-insensitive.
    """
    return normalize_path_list(raw_paths)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _reject_non_project_relative(paths: Sequence[str]) -> None:
    invalid = invalid_project_relative_paths(paths)
    if invalid:
        raise NonProjectRelativePaths(invalid)


def resolve_paths_to_target_ids(
    conn: Any,
    project_id: int | str,
    raw_paths: Iterable[str],
    *,
    project_root: Optional[Path] = None,
) -> List[int]:
    """Convert operator-supplied paths into canonical ``path_targets`` ids.

    Raises :class:`EmptyPathSet` when no paths survive normalization, or
    :class:`UnknownPathTargets` when any normalized path has no row in
    the project's Canonical Path Registry. On success returns the target
    ids in the same order the operator supplied (after deduplication).
    ``project_root`` is retained for older callers; symlink expansion is
    resolved from synced snapshot facts.
    """
    paths = _normalize_paths(raw_paths)
    if not paths:
        raise EmptyPathSet("at least one project-relative path is required")
    _reject_non_project_relative(paths)
    resolved_project_id = resolve_project_id(conn, project_id)
    paths, _ = expand_symlinks_from_snapshot_facts(
        conn, resolved_project_id, paths,
    )
    _reject_non_project_relative(paths)
    resolved: List[int] = []
    missing: List[str] = []
    for path_string in paths:
        target_id = target_at(conn, resolved_project_id, path_string)
        if target_id is None:
            missing.append(path_string)
        else:
            resolved.append(target_id)
    if missing:
        raise UnknownPathTargets(resolved_project_id, missing)
    return resolved


def resolve_or_plan_paths_to_target_ids(
    conn: Any,
    project_id: int | str,
    raw_paths: Iterable[str],
    *,
    item_id: Optional[int] = None,
    claim_id: Optional[int] = None,
    session_id: Optional[str] = None,
    directory_paths: Optional[Sequence[str]] = None,
    tentative_paths: Optional[Sequence[str]] = None,
    project_root: Optional[Path] = None,
) -> List[int]:
    """Future-aware sibling of :func:`resolve_paths_to_target_ids`.

    Each path is resolved against the Canonical Path Registry. Unknown
    paths in ``raw_paths`` are planned via
    :func:`yoke_core.domain.path_targets_materialization.plan_path_target`
    so the caller — typically the path-claim on-ramp at idea / refine
    time — can declare coverage over a future file before git has ever
    observed it. Existing observed targets are reused verbatim;
    existing planned targets are reused (with attribution backfill);
    abandoned targets are re-planned in place.

    Pass ``tentative_paths`` to mark a subset of ``raw_paths`` as
    *tentative* coverage — predicted-but-uncertain exact paths that
    participate in overlap detection and render distinctly, but are
    not a missed promise when the implementation never touches them.
    Tentative paths must also appear in ``raw_paths`` to be claimed
    (the function does not auto-merge a separate tentative-only list).

    Path kind defaults to ``file``. Pass ``directory_paths`` to mark a
    subset as directory targets — useful when operators claim a future
    directory like ``runtime/api/domain/migrations/`` separately from
    files inside it.

    ``project_root`` is retained for older callers; symlink expansion is
    resolved from synced snapshot facts.
    """
    from yoke_core.domain.path_targets_materialization import (
        plan_path_target,
        plan_tentative_path_target,
    )

    paths = _normalize_paths(raw_paths)
    if not paths:
        raise EmptyPathSet("at least one project-relative path is required")
    _reject_non_project_relative(paths)
    resolved_project_id = resolve_project_id(conn, project_id)
    paths, _ = expand_symlinks_from_snapshot_facts(
        conn, resolved_project_id, paths,
    )
    _reject_non_project_relative(paths)
    dir_set = {p.strip() for p in (directory_paths or []) if (p or "").strip()}
    tentative_set = {
        p.strip() for p in (tentative_paths or []) if (p or "").strip()
    }
    resolved: List[int] = []
    for path_string in paths:
        target_id = target_at(conn, resolved_project_id, path_string)
        if target_id is not None and _materialization_state(
            conn, target_id
        ) == _OBSERVED:
            resolved.append(target_id)
            continue
        kind = KIND_DIRECTORY if path_string in dir_set else KIND_FILE
        planner = (
            plan_tentative_path_target
            if path_string in tentative_set
            else plan_path_target
        )
        resolved.append(
            planner(
                conn,
                project_id=resolved_project_id,
                path_string=path_string,
                kind=kind,
                item_id=item_id,
                claim_id=claim_id,
                session_id=session_id,
            )
        )
    return resolved


def _materialization_state(conn: Any, target_id: int) -> str:
    p = _p(conn)
    row = conn.execute(
        "SELECT COALESCE(materialization_state, 'observed') "
        f"FROM path_targets WHERE id = {p}",
        (target_id,),
    ).fetchone()
    return _OBSERVED if row is None else str(row[0])


__all__ = [
    "EmptyPathSet",
    "NonProjectRelativePaths",
    "PathResolveError",
    "SymlinkDecision",
    "SYMLINK_CANONICALIZED",
    "SYMLINK_DANGLING_TARGET",
    "SYMLINK_EXTERNAL_TARGET",
    "UnknownPathTargets",
    "expand_symlinks_to_canonical",
    "resolve_or_plan_paths_to_target_ids",
    "resolve_paths_to_target_ids",
]
