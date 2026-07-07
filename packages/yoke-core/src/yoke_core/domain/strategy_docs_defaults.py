"""Cold-start placeholder canon + seeding for per-project strategy docs.

A project's strategy corpus is exactly its ``strategy_docs`` rows — there
is no global slug canon. This module owns the DEFAULT starter set minted
for a project with zero rows: fill-me-in scaffolds (the
:mod:`yoke_core.domain.project_contract` runbook style) parameterized
by the project display name, written DB-first by :func:`seed_default_docs`
and only ever rendered to files FROM those rows.

Seeding is strictly cold-start: a project with any existing row is left
untouched (idempotent re-runs report ``already_seeded``). Exposed as the
``strategy.seed_defaults.run`` function id; the install bundle calls the
same seeder so a fresh external install always receives a starter corpus.
"""

from __future__ import annotations

from typing import Any, Dict, List

DEFAULT_STRATEGY_DOC_SLUGS = ("MISSION", "VISION", "MASTER-PLAN", "LANDSCAPE")


def render_mission_placeholder(display_name: str) -> str:
    return f"""# Mission: {display_name}

The invariant anchor: why {display_name} exists. One or two paragraphs
that survive every strategy revision below them.

TODO: state the mission — the durable problem this project exists to
solve and for whom. Keep it short enough to recite.
"""


def render_vision_placeholder(display_name: str) -> str:
    return f"""# Vision: {display_name}

Where {display_name} is going and what it looks like when it works.
Nearer horizons should be more concrete.

## Near term

TODO: the next meaningful capability milestones and what they unlock.

## Long term

TODO: the end state — what exists, who uses it, and why it matters.
"""


def render_master_plan_placeholder(display_name: str) -> str:
    return f"""# Master Plan: {display_name}

The ordered frontier: what gets built, in what order, and why that
order. Strategy sessions keep this reconciled with delivered reality.

## Current generation

TODO: name the current generation/phase of work and its goal.

## Frontier

TODO: the ordered next items/epics with one line each on why now.

## Done / reflected

TODO: landed work worth remembering at the strategy level.
"""


def render_landscape_placeholder(display_name: str) -> str:
    return f"""# Landscape: {display_name}

The world {display_name} operates in: competitors, adjacent tools,
technical constraints, and signals worth tracking. Weave new signal
into existing sections; retire stale claims.

## Players and alternatives

TODO: who else solves this problem and how their approach differs.

## Constraints and currents

TODO: technical, market, or ecosystem facts that shape sequencing.
"""


_PLACEHOLDER_RENDERERS = {
    "MISSION": render_mission_placeholder,
    "VISION": render_vision_placeholder,
    "MASTER-PLAN": render_master_plan_placeholder,
    "LANDSCAPE": render_landscape_placeholder,
}


def placeholder_content(slug: str, display_name: str) -> str:
    """Render one default doc's placeholder scaffold."""
    try:
        renderer = _PLACEHOLDER_RENDERERS[slug]
    except KeyError:
        raise ValueError(
            f"no placeholder renderer for slug {slug!r}; default canon: "
            f"{', '.join(DEFAULT_STRATEGY_DOC_SLUGS)}"
        ) from None
    return renderer(display_name)


def seed_default_docs(
    conn: Any, project_id: int, display_name: str,
) -> Dict[str, Any]:
    """Mint placeholder rows for a project with zero strategy rows.

    DB-first cold start: rows are the authority, files render from them
    afterwards. Idempotent — any existing row for the project means the
    corpus is already established and nothing is written (``seeded`` is
    empty and ``already_seeded`` is true). Commits on write.
    Backend-aware (the install-bundle fixtures drive it over sqlite).
    """
    from yoke_core.domain.project_identity import placeholder
    from yoke_core.domain.strategy_docs import (
        STRATEGY_DOCS_TABLE,
        next_updated_at,
    )

    p = placeholder(conn)
    row = conn.execute(
        f"SELECT COUNT(*) FROM {STRATEGY_DOCS_TABLE} WHERE project_id = {p}",
        (project_id,),
    ).fetchone()
    existing = int(row[0]) if row else 0
    if existing:
        return {
            "project_id": project_id,
            "seeded": [],
            "existing_rows": existing,
            "already_seeded": True,
        }
    seeded: List[str] = []
    updated_at = next_updated_at()
    for slug in DEFAULT_STRATEGY_DOC_SLUGS:
        conn.execute(
            f"INSERT INTO {STRATEGY_DOCS_TABLE} "
            "(project_id, slug, content, updated_at) "
            f"VALUES ({p}, {p}, {p}, {p})",
            (project_id, slug, placeholder_content(slug, display_name), updated_at),
        )
        seeded.append(slug)
    conn.commit()
    return {
        "project_id": project_id,
        "seeded": seeded,
        "existing_rows": 0,
        "already_seeded": False,
    }


__all__ = [
    "DEFAULT_STRATEGY_DOC_SLUGS",
    "placeholder_content",
    "render_landscape_placeholder",
    "render_master_plan_placeholder",
    "render_mission_placeholder",
    "render_vision_placeholder",
    "seed_default_docs",
]
