"""Retired per-surface actor label projection and its name-matching lookups.

An actor's name lived in ``actor_labels``, once per surface: ``display``
for operator views and ``github_label`` for issue attribution. The two
held the same string for every actor that had both, and the second was
unique — so it doubled as a lookup key, and code that needed "which
actor is this?" answered it by matching a name. That made a rename move
an identity and made two people who share a name impossible.

One ``actors.name`` column replaces the projection, carries no
uniqueness, and resolves nothing. The helpers that rendered or resolved
a label are retired with the table; identity is ``actors.id``, and
``actors.resolve_actors_by_name`` is an operator search returning a list
rather than a resolution.

The OS-login rung that once picked a session's actor by matching that
login against a label is retired here too: a machine records the actor
id it operates its universe as, and reads it back by id.
"""

from __future__ import annotations

from yoke_core.domain.agents_render_conditional import RENDERED_AGENT_DIRS

_RETIRED_LABEL_TABLE = r"\bactor" + r"_labels\b"
_RETIRED_LABEL_SURFACE_CONSTANT = (
    r"\b(DISPLAY" + r"_LABEL_SURFACE|GITHUB" + r"_LABEL_SURFACE"
    r"|RESOLUTION" + r"_LABEL_SURFACES)\b"
)
_RETIRED_LABEL_HELPER = (
    r"\bactors\.(actor" + r"_label|set" + r"_actor_label"
    r"|resolve" + r"_actor_by_label|labels" + r"_for_surface"
    r"|actor" + r"_label_or_passthrough)\b"
)
_RETIRED_DISPLAY_MODULE = r"\bactor" + r"_display\b"
_RETIRED_DISPLAY_HELPER = (
    r"\b(actor" + r"_display_name|set" + r"_actor_display_name"
    r"|actor" + r"_render_label)\b"
)
_RETIRED_LABEL_EXCEPTION = r"\bActorLabel(Missing|Ambiguous)\b"
_RETIRED_LOCAL_HUMAN_LABEL = (
    r"\b(LOCAL" + r"_HUMAN_LABEL_ENV|YOKE" + r"_LOCAL_HUMAN_LABEL"
    r"|DEFAULT" + r"_LOCAL_HUMAN_LABEL|DEFAULT" + r"_ADMIN_ACTOR_LABEL)\b"
)
_RETIRED_RESOLUTION_INDEX = r"\bRESOLUTION" + r"_LABEL_INDEX\b"

ACTOR_NAME_RETIREMENT_PATTERNS: tuple[str, ...] = (
    _RETIRED_LABEL_TABLE,
    _RETIRED_LABEL_SURFACE_CONSTANT,
    _RETIRED_LABEL_HELPER,
    _RETIRED_DISPLAY_MODULE,
    _RETIRED_DISPLAY_HELPER,
    _RETIRED_LABEL_EXCEPTION,
    _RETIRED_LOCAL_HUMAN_LABEL,
    _RETIRED_RESOLUTION_INDEX,
)

ACTOR_NAME_RETIREMENT_LABELS: dict[str, str] = {
    _RETIRED_LABEL_TABLE: (
        "actor label projection table (retired — one actors.name column "
        "carries the name every surface renders)"
    ),
    _RETIRED_LABEL_SURFACE_CONSTANT: (
        "actor label surface vocabulary (retired — a name has no surfaces)"
    ),
    _RETIRED_LABEL_HELPER: (
        "actor label read/write helpers (retired — use actors.actor_name, "
        "actors.set_actor_name, actors.actor_name_or_passthrough)"
    ),
    _RETIRED_DISPLAY_MODULE: (
        "actor_display module (retired — naming lives in actors)"
    ),
    _RETIRED_DISPLAY_HELPER: (
        "actor display-name helpers (retired — use actors.actor_name, or "
        "actor_render.render_actor_name for the fail-open view rendering)"
    ),
    _RETIRED_LABEL_EXCEPTION: (
        "actor label exceptions (retired — a missing name is not an error; "
        "an unknown actor raises ActorNotFound)"
    ),
    _RETIRED_LOCAL_HUMAN_LABEL: (
        "local-human and admin actor label constants (retired — the seeding "
        "names use YOKE_LOCAL_HUMAN_NAME / DEFAULT_LOCAL_HUMAN_NAME / "
        "DEFAULT_ADMIN_ACTOR_NAME, and none of them selects an actor)"
    ),
    _RETIRED_RESOLUTION_INDEX: (
        "actor label resolution uniqueness index (retired — actors.name "
        "carries no uniqueness because it resolves nothing)"
    ),
}

#: Surfaces whose subject IS this retirement: the history entry that drops
#: the projection and its test, the decision record explaining why, and the
#: agent packet, which cannot warn the next agent off a retired spelling
#: without writing that spelling down. Every rendered harness adapter
#: mirrors that packet body verbatim, so the exemption follows the
#: renderer's own directory registry rather than a hand-kept list —
#: onboarding a harness must not turn this check red.
_RETIREMENT_SUBJECT_PATHS: tuple[str, ...] = (
    # This module spells every retired name out as a literal, so it is as
    # self-referential as the catalogue that loads it.
    "packages/yoke-core/src/yoke_core/engines/doctor_hc_obsoleted_terms_actor_name.py",
    "packages/yoke-core/src/yoke_core/domain/migrations/",
    "runtime/api/domain/test_migration_actor_name_replaces_labels.py",
    # Proves what the entry that RELAXED the old projection's uniqueness did,
    # which cannot be asserted without naming the surfaces it acted on.
    "runtime/api/domain/test_migration_actor_display_label.py",
    "packages/yoke-core/src/yoke_core/domain/schema_api_context_tables_actors.py",
    "docs/archive/decisions/actor-name-is-not-an-identity.md",
) + tuple(f"{directory.as_posix()}/" for directory in RENDERED_AGENT_DIRS)

ACTOR_NAME_RETIREMENT_ALLOWLIST: dict[str, tuple[str, ...]] = {
    pattern: _RETIREMENT_SUBJECT_PATHS
    for pattern in ACTOR_NAME_RETIREMENT_PATTERNS
}

__all__ = [
    "ACTOR_NAME_RETIREMENT_ALLOWLIST",
    "ACTOR_NAME_RETIREMENT_LABELS",
    "ACTOR_NAME_RETIREMENT_PATTERNS",
]
