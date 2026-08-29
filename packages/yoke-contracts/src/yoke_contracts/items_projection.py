"""Field vocabulary for the ``items.get`` projection.

Two surfaces have to agree on this list and only one of them can import
the engine: ``yoke items get --help`` renders the accepted names so an
agent can pick one without a round trip, and the read handler names them
again when it refuses a token it does not recognise. Holding the
vocabulary here is what lets the help text and the refusal quote the same
set.

``yoke_core.domain.items_constants`` re-exports :data:`CANONICAL_COLUMNS`
and :data:`STRUCTURED_FIELDS` so engine callers keep their existing import
site.
"""

from __future__ import annotations

from difflib import get_close_matches
from typing import Iterable, Sequence

# Canonical column order for pipe-delimited row output.
# "body" is a virtual field rendered on demand.
CANONICAL_COLUMNS: tuple[str, ...] = (
    "id",
    "title",
    "workflow_id",
    "workflow_version_id",
    "status",
    "priority",
    "frozen",
    "github_issue",
    "deployed_to",
    "body",
    "merged_at",
    "created_at",
    "updated_at",
    "source",
    "project",
    "project_id",
    "project_sequence",
    "deployment_flow",
    "deploy_stage",
)

# Structured fields (large text that accepts file-based writes).
STRUCTURED_FIELDS: frozenset[str] = frozenset(
    {
        "spec",
        "design_spec",
        "technical_plan",
        "worktree_plan",
        "shepherd_log",
        "shepherd_caveats",
        "test_results",
        "deploy_log",
        "db_mutation_profile",
        "db_compatibility_attestation",
        "architecture_impact",
    }
)

# Scalar columns surfaced by the schema packet but outside the pipe-row
# layout. Listing them keeps the packet promise honest — every items
# column the packet teaches is readable through ``items.get`` without a
# round trip through a raw SELECT.
ADDITIONAL_SCALAR_FIELDS: frozenset[str] = frozenset(
    {
        "blocked",
        "blocked_reason",
        "owner",
        "resolution",
        "resolution_ref",
        "resolution_comment",
        "spec_updated_at",
        "spec_updated_by",
        "merge_queue_pr_number",
        "merge_queue_enqueued_at",
        "merge_queue_landed_at",
        "merge_queue_notified_at",
    }
)

ADDITIONAL_VIRTUAL_FIELDS: frozenset[str] = frozenset({"merge_queue_status"})

ALLOWED_GET_FIELDS: frozenset[str] = (
    frozenset(CANONICAL_COLUMNS)
    | STRUCTURED_FIELDS
    | ADDITIONAL_SCALAR_FIELDS
    | ADDITIONAL_VIRTUAL_FIELDS
)

# Default projection when the caller names no fields: every allowed field,
# in a stable order. Canonical columns alone omitted the structured fields
# and additional scalars, which made `yoke items get ITEM --json` look like
# technical_plan was missing.
DEFAULT_GET_FIELDS: tuple[str, ...] = (
    tuple(CANONICAL_COLUMNS)
    + tuple(sorted(STRUCTURED_FIELDS))
    + tuple(sorted(ADDITIONAL_SCALAR_FIELDS))
    + tuple(sorted(ADDITIONAL_VIRTUAL_FIELDS))
)

# Names an agent is most likely to reach for that are not columns at all.
# Each maps to the surface that does answer the question, so a wrong guess
# ends in a command rather than another guess.
_NON_FIELD_REDIRECTS: dict[str, str] = {
    "detail": "yoke items detail get ITEM --json",
    "workflow": "yoke workflows item get ITEM --json",
    "claim": "yoke claims work holder-get ITEM",
    "claims": "yoke claims work holder-get ITEM",
    "worktree": "yoke item-worktrees get ITEM --lane-role implementation",
    "worktrees": "yoke item-worktrees get ITEM --lane-role implementation",
    "dependencies": "yoke shepherd dependency-list ITEM",
}


def render_field_catalog(*, indent: str = "  ") -> str:
    """Render the accepted field names, grouped the way they are stored."""
    groups: Sequence[tuple[str, Iterable[str]]] = (
        ("columns", CANONICAL_COLUMNS),
        ("structured text", sorted(STRUCTURED_FIELDS)),
        ("additional scalars", sorted(ADDITIONAL_SCALAR_FIELDS)),
        ("virtual", sorted(ADDITIONAL_VIRTUAL_FIELDS)),
    )
    lines = ["Accepted fields (omit all to read every one):"]
    for label, names in groups:
        lines.append(f"{indent}{label}: {', '.join(names)}")
    return "\n".join(lines)


def unknown_field_message(token: str) -> str:
    """Render the refusal for an unrecognised ``items.get`` field token.

    Names the accepted set every time, and leads with the specific
    surface when the token is a familiar non-column guess or a near-miss
    on a real field.
    """
    lines = [f"unknown items column {token!r}"]
    redirect = _NON_FIELD_REDIRECTS.get(str(token).strip().casefold())
    if redirect:
        lines.append(f"{token!r} is not an items column; read it with: {redirect}")
    else:
        near = get_close_matches(
            str(token),
            sorted(ALLOWED_GET_FIELDS),
            n=3,
            cutoff=0.6,
        )
        if near:
            lines.append(f"Did you mean: {', '.join(near)}?")
    lines.append(render_field_catalog())
    return "\n".join(lines)


__all__ = [
    "ADDITIONAL_SCALAR_FIELDS",
    "ADDITIONAL_VIRTUAL_FIELDS",
    "ALLOWED_GET_FIELDS",
    "CANONICAL_COLUMNS",
    "DEFAULT_GET_FIELDS",
    "STRUCTURED_FIELDS",
    "render_field_catalog",
    "unknown_field_message",
]
