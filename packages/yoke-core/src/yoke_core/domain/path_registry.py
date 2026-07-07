"""Canonical Path Registry — identity layer for committed repo paths.

Owns ``path_targets`` identity, parent/child traversal, and the
``target_at`` binding helper. HEAD snapshot building lives in sibling
:mod:`yoke_core.domain.path_snapshots`. The CPR has one job: give every
committed path in a project's repo a Yoke-owned identity. It reads git;
it does not read Project Structure or any other coordination layer.

Constitution
============

C1 — Location identity: a ``path_target_id`` identifies a canonical repo
location, not an enduring "soul of the file." Distinct paths get distinct
ids even when a rename connects them; claims follow work by rebinding
through explicit continuity edges (per C2), not by mutating
``path_string``. Rows are immutable facts, liveness is snapshot-derived
(C4), and a stable id is stable within one path-string generation.

C2 — Structural continuity grain: path continuity layer's ``path_moves`` may describe a
subtree-root continuity fact. Descendant continuity is inherited by
deterministic structural projection through path registry identity layer's parent/child links, with
the most specific continuity fact winning. path registry identity layer ships only the substrate:
``path_targets.parent_target_id`` plus ``ancestors_of`` /
``descendants_of``. ``path_moves`` itself is path continuity layer.

C3 — Open-world on inheritance failure: when inherited continuity projects
a descendant successor to a target absent from the current complete
snapshot and no more-specific continuity record exists, the registry
returns ``continuity_unknown``, not ``upstream_delete``. Absence alone is
not deletion; ``continuity_unknown`` is a legitimate terminal status.

C4 — Path lifecycle is snapshot-derived: a ``path_target`` is immutable
coordinate identity. Presence in a complete commit-scoped snapshot means
live at that commit; absence means not live. Deletes do not change an
identity column. Renames use a new target plus path continuity layer continuity. A same path
string reappearing after an observed disappearance mints a new generation.
There is no tombstone table, ``tombstoned_at`` column, or ``tombstoned``
snapshot status at path registry identity layer.

C5 — Recording authority: Yoke may record observations, but should not
record inferences. The scanner records factual git observations only:
adds mint targets, deletes are absence in a later complete snapshot, and
identity exists for every committed path at the snapshotted commit.
Continuity edges answer an inferential question ("was this delete + add
the same conceptual file?") and land only via Yoke-observed workflow
events or explicit operator adjudication. The scanner must not use git
rename / similarity detection, even as hidden scaffolding. Yoke's
identity layer mirrors git; continuity/context layers mirror authored
workflow or operator truth.
"""

from __future__ import annotations

from typing import Any, Iterable, List, Optional, Tuple

from yoke_contracts.path_snapshot import (
    KIND_DIRECTORY,
    KIND_FILE,
    ROOT_PATH_SENTINEL,
    all_paths_with_kinds as _contract_all_paths_with_kinds,
    parent_path_string as _contract_parent_path_string,
)
from yoke_core.domain import db_backend
from yoke_core.domain.project_identity import resolve_project_id


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _parent_path_string(path_string: str) -> Optional[str]:
    """Return the parent path string for a project-relative POSIX path,
    or ``None`` when ``path_string`` is the root sentinel.

    Top-level paths have the root sentinel as their parent.
    """
    return _contract_parent_path_string(path_string)


def _all_paths_with_kinds(
    file_paths: Iterable[str],
) -> List[Tuple[str, str]]:
    """Derive every ``(path_string, kind)`` tuple needed to materialize
    whole-repo identity from a list of committed file paths.

    The result is the union of:

    * the root sentinel (always present, ``directory``)
    * each committed file (``file``)
    * every directory ancestor required to chain those files to the root
      (``directory``)

    Ordering is deterministic: root first, directories sorted by length
    then lexicographically (so each parent precedes its children),
    then files sorted lexicographically.  This keeps mint order
    deterministic and lets the caller resolve parent IDs by-row without
    a lookahead pass.
    """
    return _contract_all_paths_with_kinds(file_paths)


def target_at(
    conn: Any,
    project_id: int | str,
    path_string: str,
) -> Optional[int]:
    """Return the *latest* ``path_target_id`` for a project-relative
    POSIX path string, or ``None`` when the registry has never observed
    it.  This is the canonical bind helper for downstream consumers
    (claims, durable context, future symbol-level identity).
    """
    p = _p(conn)
    resolved_project_id = resolve_project_id(conn, project_id)
    row = conn.execute(
        "SELECT id FROM path_targets "
        f"WHERE project_id = {p} AND path_string = {p} "
        "ORDER BY generation DESC LIMIT 1",
        (resolved_project_id, path_string),
    ).fetchone()
    if row is None:
        return None
    return int(row[0])


def ancestors_of(
    conn: Any, target_id: int
) -> List[int]:
    """Return every ancestor target id walking up ``parent_target_id``,
    nearest-first.  The target itself is not included; the chain ends
    at the root sentinel (``parent_target_id IS NULL``).
    """
    p = _p(conn)
    rows = conn.execute(
        f"""
        WITH RECURSIVE chain(id, parent_target_id, depth) AS (
            SELECT id, parent_target_id, 0
              FROM path_targets WHERE id = {p}
            UNION ALL
            SELECT t.id, t.parent_target_id, c.depth + 1
              FROM path_targets t
              JOIN chain c ON t.id = c.parent_target_id
        )
        SELECT id FROM chain WHERE depth > 0 ORDER BY depth
        """,
        (target_id,),
    ).fetchall()
    return [int(r[0]) for r in rows]


def descendants_of(
    conn: Any, target_id: int
) -> List[int]:
    """Return every descendant target id reachable through
    ``parent_target_id`` traversal.  The target itself is not included.
    """
    p = _p(conn)
    rows = conn.execute(
        f"""
        WITH RECURSIVE subtree(id) AS (
            SELECT id FROM path_targets WHERE parent_target_id = {p}
            UNION ALL
            SELECT t.id FROM path_targets t
              JOIN subtree s ON t.parent_target_id = s.id
        )
        SELECT id FROM subtree
        """,
        (target_id,),
    ).fetchall()
    return [int(r[0]) for r in rows]


def _latest_target_for_path(
    conn: Any,
    project_id: int | str,
    path_string: str,
) -> Optional[Tuple[int, int, str, Optional[int]]]:
    p = _p(conn)
    resolved_project_id = resolve_project_id(conn, project_id)
    row = conn.execute(
        "SELECT id, generation, kind, parent_target_id FROM path_targets "
        f"WHERE project_id = {p} AND path_string = {p} "
        "ORDER BY generation DESC LIMIT 1",
        (resolved_project_id, path_string),
    ).fetchone()
    if row is None:
        return None
    parent_id = None if row[3] is None else int(row[3])
    return int(row[0]), int(row[1]), str(row[2]), parent_id


def _disappearance_observed(
    conn: Any,
    project_id: int,
    target_id: int,
) -> bool:
    """Per C4: a generation bump is warranted only when the latest
    target was *present* in some snapshot and then *absent* from a
    later snapshot.  Returns True iff that trajectory has been recorded.
    """
    p = _p(conn)
    last_present = conn.execute(
        "SELECT MAX(s.id) FROM path_snapshots s "
        "JOIN path_snapshot_entries e ON e.snapshot_id = s.id "
        f"WHERE s.project_id = {p} AND e.target_id = {p}",
        (project_id, target_id),
    ).fetchone()[0]
    if last_present is None:
        return False
    later_absent = conn.execute(
        "SELECT 1 FROM path_snapshots s "
        f"WHERE s.project_id = {p} AND s.id > {p} "
        "  AND NOT EXISTS ("
        "    SELECT 1 FROM path_snapshot_entries e "
        f"    WHERE e.snapshot_id = s.id AND e.target_id = {p}"
        "  ) LIMIT 1",
        (project_id, last_present, target_id),
    ).fetchone()
    return later_absent is not None


def _mint_target(
    conn: Any,
    project_id: int,
    path_string: str,
    kind: str,
    parent_target_id: Optional[int],
    generation: int,
    now_iso: str,
) -> int:
    p = _p(conn)
    cur = conn.execute(
        "INSERT INTO path_targets "
        "(project_id, kind, path_string, generation, "
        f"parent_target_id, created_at) VALUES ({p}, {p}, {p}, {p}, {p}, {p}) "
        "RETURNING id",
        (
            project_id,
            kind,
            path_string,
            generation,
            parent_target_id,
            now_iso,
        ),
    )
    return int(cur.fetchone()[0])


def _resolve_path_target_id(
    conn: Any,
    project_id: int,
    path_string: str,
    kind: str,
    parent_target_id: Optional[int],
    now_iso: str,
) -> int:
    """Find or mint the active path_target for ``path_string`` per C4.

    * No prior row: mint generation 1.
    * Latest row exists and no disappearance has been observed since
      it was last present: reuse.
    * Latest row exists and a disappearance has been observed: mint a
      new generation.

    The disappearance check reads ``path_snapshot_entries``; on the
    very first scan (no snapshots yet) the trajectory is degenerate
    and the existing row is reused.
    """
    latest = _latest_target_for_path(conn, project_id, path_string)
    if latest is None:
        return _mint_target(
            conn,
            project_id,
            path_string,
            kind,
            parent_target_id,
            1,
            now_iso,
        )
    target_id, generation, latest_kind, latest_parent_id = latest
    if latest_kind != kind or latest_parent_id != parent_target_id:
        return _mint_target(
            conn,
            project_id,
            path_string,
            kind,
            parent_target_id,
            generation + 1,
            now_iso,
        )
    if _disappearance_observed(conn, project_id, target_id):
        return _mint_target(
            conn,
            project_id,
            path_string,
            kind,
            parent_target_id,
            generation + 1,
            now_iso,
        )
    return target_id


__all__ = [
    "KIND_DIRECTORY",
    "KIND_FILE",
    "ROOT_PATH_SENTINEL",
    "ancestors_of",
    "descendants_of",
    "target_at",
]
