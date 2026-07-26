"""Default placeholder canon + per-slug seeding for project strategy docs.

A project's strategy corpus is exactly its ``strategy_docs`` rows — there
is no global slug canon. This module owns the DEFAULT starter set:
fill-me-in scaffolds (the :mod:`yoke_core.domain.project_contract`
runbook style) parameterized by the project display name, written
DB-first by :func:`seed_default_docs` and only ever rendered to files
FROM those rows.

Seeding is a per-slug top-up: each missing default slug gains its
placeholder row, and an existing row — whatever its content — is never
touched. A fresh project cold-starts the full roster; an established
project heals by gaining only the default slugs it is missing. Exposed
as the ``strategy.seed_defaults.run`` function id; the install bundle
calls the same seeder so a fresh external install always receives a
starter corpus and an existing install tops up on refresh.
"""

from __future__ import annotations

from typing import Any, Dict, List

DEFAULT_STRATEGY_DOC_SLUGS = (
    "MISSION", "VISION", "MASTER-PLAN", "LANDSCAPE", "CURRENT-PLAN",
)


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


def render_current_plan_placeholder(display_name: str) -> str:
    return f"""# Current Plan: {display_name}

The near-term executable slice: what ships next and how to tell it
shipped. First-work seeding derives backlog items from this doc.

## Now

TODO: the current goal and the concrete work that reaches it.

## Next

TODO: what follows once the current slice lands.

## Done when

TODO: the observable outcomes that close this plan.
"""


_PLACEHOLDER_RENDERERS = {
    "MISSION": render_mission_placeholder,
    "VISION": render_vision_placeholder,
    "MASTER-PLAN": render_master_plan_placeholder,
    "LANDSCAPE": render_landscape_placeholder,
    "CURRENT-PLAN": render_current_plan_placeholder,
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
    """Top up the project's default strategy docs, seeding only missing slugs.

    DB-first: rows are the authority, files render from them afterwards.
    Idempotent per slug — an existing row for a default slug (whatever
    its content, live or archived) is never touched; each missing
    default slug gains its placeholder. ``seeded`` names the slugs
    written by this call, ``already_present`` the default slugs that
    already had a row, and ``already_seeded`` is true when nothing was
    missing. Commits on write. Backend-aware (the install-bundle
    fixtures drive it over sqlite).
    """
    from yoke_core.domain.project_identity import placeholder
    from yoke_core.domain.strategy_docs import (
        STRATEGY_DOCS_TABLE,
        next_updated_at,
    )

    p = placeholder(conn)
    slug_ph = ", ".join(p for _ in DEFAULT_STRATEGY_DOC_SLUGS)
    rows = conn.execute(
        f"SELECT slug FROM {STRATEGY_DOCS_TABLE} "
        f"WHERE project_id = {p} AND slug IN ({slug_ph})",
        (project_id, *DEFAULT_STRATEGY_DOC_SLUGS),
    ).fetchall()
    present = {str(row[0]) for row in rows or []}
    already_present = [
        slug for slug in DEFAULT_STRATEGY_DOC_SLUGS if slug in present
    ]
    seeded: List[str] = []
    updated_at = next_updated_at()
    for slug in DEFAULT_STRATEGY_DOC_SLUGS:
        if slug in present:
            continue
        conn.execute(
            f"INSERT INTO {STRATEGY_DOCS_TABLE} "
            "(project_id, slug, content, updated_at) "
            f"VALUES ({p}, {p}, {p}, {p})",
            (project_id, slug, placeholder_content(slug, display_name), updated_at),
        )
        seeded.append(slug)
    if seeded:
        conn.commit()
    return {
        "project_id": project_id,
        "seeded": seeded,
        "already_present": already_present,
        "existing_rows": len(already_present),
        "already_seeded": not seeded,
    }


__all__ = [
    "DEFAULT_STRATEGY_DOC_SLUGS",
    "placeholder_content",
    "render_current_plan_placeholder",
    "render_landscape_placeholder",
    "render_master_plan_placeholder",
    "render_mission_placeholder",
    "render_vision_placeholder",
    "seed_default_docs",
]
