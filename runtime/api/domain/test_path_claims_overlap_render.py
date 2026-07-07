"""Render-target pre-check tests for the overlap classifier.

Split from `test_path_claims_overlap.py` so the parent stays under the
350-line gate. Covers:

* Overlap on `FAMILY_RENDER_TARGET` paths with disjoint seed-source
  coverage auto-classifies as `NONE` (no operator-authored
  coordination_only edges required).
* Overlap on render-target paths whose seed sources also overlap
  preserves the existing `INCOMPATIBLE` semantics.
* Hand-authored overlap is unaffected by the pre-check.
* Mixed render-target + hand-authored overlap falls through to the
  normal classifier.
* Disjoint-stanza regression: two candidates editing disjoint
  `schema_api_context_*.py` stanzas register cleanly.
"""

from __future__ import annotations

from yoke_core.domain._path_claims_test_helpers import (
    conn,  # noqa: F401  (pytest fixture)
    local_human,
    seed_target,
)
from yoke_core.domain.path_claims import register
from yoke_core.domain.path_claims_overlap import (
    OverlapClassification,
    classify_overlap,
)

_CORE_DOMAIN_SOURCE_ROOT = "packages/yoke-core/src/yoke_core/domain"


def _ensure_target(conn, *, path_string: str) -> int:
    row = conn.execute(
        "SELECT t.id FROM path_targets t "
        "JOIN projects p ON p.id = t.project_id "
        "WHERE p.slug='yoke' AND t.path_string=%s "
        "ORDER BY t.generation DESC LIMIT 1",
        (path_string,),
    ).fetchone()
    return int(row[0]) if row else seed_target(conn, path_string=path_string)


def _seed_render_target(conn, *, rendered_path, source_paths, event_id):
    from yoke_core.domain.path_context import put_context_value
    target_id = _ensure_target(conn, path_string=rendered_path)
    for src in source_paths:
        _ensure_target(conn, path_string=src)
    conn.execute(
        "INSERT INTO events (event_id, event_name, event_kind, "
        "event_type, source_type, session_id, severity, event_outcome, "
        "created_at) VALUES (%s, 'RenderRelationshipRecorded', 'lifecycle', "
        "'path_context', 'backend', '', 'INFO', 'completed', "
        "'2026-05-01T00:00:00Z') ON CONFLICT(event_id) DO NOTHING",
        (event_id,),
    )
    put_context_value(
        conn, target_id=target_id, context_family="render_target",
        entry_key="", value={"sources": sorted(source_paths)},
        recorded_event_id=event_id,
    )
    return target_id


class TestRenderTargetOverlapClassifier:
    def test_disjoint_seeds_on_render_target_yield_none(self, conn):
        actor = local_human(conn)
        rendered = _seed_render_target(
            conn,
            rendered_path="runtime/harness/claude/agents/yoke-architect.md",
            source_paths=[
                f"{_CORE_DOMAIN_SOURCE_ROOT}/schema_api_context_tables_core.py",
                f"{_CORE_DOMAIN_SOURCE_ROOT}/schema_api_context_tables_claims.py",
            ],
            event_id="ev-disjoint",
        )
        other = _ensure_target(
            conn, path_string=f"{_CORE_DOMAIN_SOURCE_ROOT}/schema_api_context_tables_core.py",
        )
        register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[rendered, other],
        )
        candidate = int(conn.execute(
            "SELECT id FROM path_targets WHERE path_string=%s",
            (f"{_CORE_DOMAIN_SOURCE_ROOT}/schema_api_context_tables_claims.py",),
        ).fetchone()[0])
        assert classify_overlap(
            conn, target_ids=[rendered, candidate],
            integration_target="main", phase="register",
        ) is OverlapClassification.NONE

    def test_overlapping_seeds_on_render_target_remain_incompatible(self, conn):
        actor = local_human(conn)
        rendered = _seed_render_target(
            conn,
            rendered_path="runtime/harness/codex/agents/yoke-engineer.toml",
            source_paths=[
                f"{_CORE_DOMAIN_SOURCE_ROOT}/schema_api_context_tables_qa.py",
                f"{_CORE_DOMAIN_SOURCE_ROOT}/agents_render_subagent_hooks.py",
            ],
            event_id="ev-overlap",
        )
        shared = _ensure_target(
            conn, path_string=f"{_CORE_DOMAIN_SOURCE_ROOT}/schema_api_context_tables_qa.py",
        )
        register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[rendered, shared],
        )
        assert classify_overlap(
            conn, target_ids=[rendered, shared],
            integration_target="main", phase="register",
        ) is OverlapClassification.INCOMPATIBLE

    def test_hand_authored_overlap_unchanged_by_render_pre_check(self, conn):
        # Render pre-check must not affect non-render paths.
        actor = local_human(conn)
        target = seed_target(conn, path_string=_CORE_DOMAIN_SOURCE_ROOT)
        register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[target],
        )
        assert classify_overlap(
            conn, target_ids=[target], integration_target="main",
            phase="register",
        ) is OverlapClassification.INCOMPATIBLE

    def test_partial_render_overlap_falls_through(self, conn):
        actor = local_human(conn)
        rendered = _seed_render_target(
            conn,
            rendered_path="runtime/harness/claude/agents/yoke-tester.md",
            source_paths=[f"{_CORE_DOMAIN_SOURCE_ROOT}/schema_api_context_render.py"],
            event_id="ev-mixed",
        )
        hand = _ensure_target(
            conn, path_string=f"{_CORE_DOMAIN_SOURCE_ROOT}/path_claims.py",
        )
        register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[rendered, hand],
        )
        assert classify_overlap(
            conn, target_ids=[rendered, hand],
            integration_target="main", phase="register",
        ) is OverlapClassification.INCOMPATIBLE

    def test_sun_1781_disjoint_packet_regression(self, conn):
        # Two candidates editing disjoint schema_api_context stanzas
        # register cleanly. Overlap is on rendered packets; seeds disjoint.
        actor = local_human(conn)
        sources = [
            f"{_CORE_DOMAIN_SOURCE_ROOT}/schema_api_context_tables_project.py",
            f"{_CORE_DOMAIN_SOURCE_ROOT}/schema_api_context_tables_qa.py",
        ]
        md = _seed_render_target(
            conn,
            rendered_path="runtime/harness/claude/agents/yoke-boss.md",
            source_paths=sources, event_id="ev-1781-md",
        )
        toml = _seed_render_target(
            conn,
            rendered_path="runtime/harness/codex/agents/yoke-boss.toml",
            source_paths=sources, event_id="ev-1781-toml",
        )
        other = int(conn.execute(
            "SELECT id FROM path_targets WHERE path_string=%s", (sources[0],),
        ).fetchone()[0])
        register(
            conn, actor_id=actor, integration_target="main",
            target_ids=[md, toml, other],
        )
        candidate = int(conn.execute(
            "SELECT id FROM path_targets WHERE path_string=%s", (sources[1],),
        ).fetchone()[0])
        assert classify_overlap(
            conn, target_ids=[md, toml, candidate],
            integration_target="main", phase="register",
        ) is OverlapClassification.NONE
