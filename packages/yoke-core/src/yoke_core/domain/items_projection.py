"""Operator-facing item projection vocabulary.

The selectable fields, default listing projection and actor-label field set
are domain vocabulary: server handlers and CLI flag parsers both derive their
shapes from this module so the layers cannot drift.
"""

from __future__ import annotations

from yoke_contracts.time_sql import instant_wire_sql
from yoke_core.domain.stored_instant_columns import STORED_INSTANT_COLUMNS

ITEM_INSTANT_FIELDS = frozenset(
    column for table, column in STORED_INSTANT_COLUMNS if table == "items"
)


def item_text_expression(field: str, *, column: str | None = None) -> str:
    """Project a trusted item column for a textual query/pipe owner."""
    value = column or field
    expression = (
        instant_wire_sql(value)
        if field in ITEM_INSTANT_FIELDS
        else f"CAST({value} AS TEXT)"
    )
    return f"COALESCE({expression}, '')"


#: Columns whose emitted form is an actor display label rather than the
#: raw stored value (which is a numeric ``actors.id``). ``owner`` renders
#: name plus actor id through :mod:`yoke_core.domain.item_owner_label`.
ACTOR_LABEL_FIELDS = frozenset({"source", "owner"})

#: Default column projection for operator-facing item listings. ``id``
#: carries the public ``PREFIX-N`` ref; ``source`` carries the actor
#: display label. Item primary keys remain inside the engine.
DEFAULT_LIST_FIELDS: tuple[str, ...] = (
    "id",
    "title",
    "status",
    "priority",
    "workflow_id",
    "source",
)

DEFAULT_LIST_FIELDS_CSV = ",".join(DEFAULT_LIST_FIELDS)

__all__ = [
    "ACTOR_LABEL_FIELDS",
    "ITEM_INSTANT_FIELDS",
    "item_text_expression",
    "DEFAULT_LIST_FIELDS",
    "DEFAULT_LIST_FIELDS_CSV",
]


# Canonical field list -- "body" is a virtual rendered field
_QI_ALL_FIELDS = {
    "id",
    "title",
    "workflow_id",
    "workflow_version_id",
    "status",
    "priority",
    "frozen",
    "blocked",
    "blocked_reason",
    "github_issue",
    "deployed_to",
    "body",
    "merged_at",
    "created_at",
    "updated_at",
    "source",
    "owner",
    "project",
    "project_id",
    "project_sequence",
    "deployment_flow",
    "deploy_stage",
    "spec",
    "design_spec",
    "technical_plan",
    "worktree_plan",
    "shepherd_caveats",
    "test_results",
    "deploy_log",
    "db_mutation_profile",
    "db_compatibility_attestation",
    "architecture_impact",
    "merge_queue_pr_number",
    "merge_queue_enqueued_at",
    "merge_queue_landed_at",
    "merge_queue_notified_at",
    "merge_queue_status",
    "stage",
    "home_section",
    "next_actor",
    "progress",
}

# Rendered on demand, not stored in DB.
_QI_VIRTUAL_FIELDS = {"body", "merge_queue_status"}

_QI_DEFAULT_FIELDS = DEFAULT_LIST_FIELDS_CSV

_QI_LARGE_TEXT_FIELDS = {
    "body",
    "spec",
    "design_spec",
    "technical_plan",
    "worktree_plan",
    "shepherd_caveats",
    "test_results",
    "deploy_log",
    "db_mutation_profile",
    "db_compatibility_attestation",
    "architecture_impact",
}
