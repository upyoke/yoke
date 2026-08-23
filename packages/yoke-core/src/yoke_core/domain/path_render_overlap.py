"""Shared false-positive check for deterministic rendered path overlap."""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from yoke_core.domain.agents_render_path_context import read_render_source_for
from yoke_core.domain.conflict_survey_declared_paths import (
    clean_path,
    path_scopes_overlap,
)
from yoke_core.domain.path_registry import target_at
from yoke_core.domain.schema_common import _table_exists


def _clean_paths(paths: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(path for value in paths if (path := clean_path(value))))


def is_render_target_only_overlap(
    conn: Any,
    *,
    candidate_paths: Sequence[str],
    other_paths: Sequence[str],
    project_id: int | str,
) -> bool:
    """Return whether every overlap is rendered output with disjoint seeds.

    Exact shared paths must all carry a registered render relationship. An
    ancestor-directory match is intentionally ineligible because it may cover
    hand-authored files too. The registered seed union then proves whether the
    two complete path sets edit independent inputs. Pure regenerations have
    empty seed slices on both sides and are therefore independent.
    """
    if not all(
        _table_exists(conn, table) for table in ("path_targets", "path_context_values")
    ):
        return False
    candidate = _clean_paths(candidate_paths)
    other = _clean_paths(other_paths)
    overlaps = [
        (left, right)
        for left in candidate
        for right in other
        if path_scopes_overlap(left, right)
    ]
    if not overlaps or any(left != right for left, right in overlaps):
        return False

    seed_sources: set[str] = set()
    for shared_path in {left for left, _right in overlaps}:
        target_id = target_at(conn, project_id, shared_path)
        if target_id is None:
            return False
        sources = read_render_source_for(conn, target_id=target_id)
        if not sources:
            return False
        seed_sources.update(_clean_paths(sources))

    candidate_seeds = set(candidate) & seed_sources
    other_seeds = set(other) & seed_sources
    return candidate_seeds.isdisjoint(other_seeds)


__all__ = ["is_render_target_only_overlap"]
