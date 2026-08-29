"""Field-set constants and filter-parsing helpers for items query commands.

Owns the canonical field allowlist (`_QI_ALL_FIELDS`, `_QI_VIRTUAL_FIELDS`,
`_QI_DEFAULT_FIELDS`, `_QI_LARGE_TEXT_FIELDS`) and the parsers that translate
CLI flag arrays into ``queries.ItemFilter`` plus field/limit selections
(`_parse_item_id`, `_parse_item_filters`, `_validate_fields`).

These helpers are shared between the items listing/read commands and the
backlog list-cli renderer, so they live in their own canonical module to
satisfy the no-two-hop shim invariant.
"""

from __future__ import annotations

import sys

from yoke_core.api.service_client_shared import queries
from yoke_core.domain.items_projection import DEFAULT_LIST_FIELDS_CSV


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
    "internal_id",
    "deployment_flow",
    "deploy_stage",
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
    "merge_queue_pr_number",
    "merge_queue_enqueued_at",
    "merge_queue_landed_at",
    "merge_queue_notified_at",
    "merge_queue_status",
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
    "shepherd_log",
    "shepherd_caveats",
    "test_results",
    "deploy_log",
    "db_mutation_profile",
    "db_compatibility_attestation",
    "architecture_impact",
}

__all__ = [
    "_QI_ALL_FIELDS",
    "_QI_VIRTUAL_FIELDS",
    "_QI_DEFAULT_FIELDS",
    "_QI_LARGE_TEXT_FIELDS",
    "_parse_item_id",
    "_parse_item_filters",
    "_validate_fields",
]


def _parse_item_id(raw: str) -> str | None:
    """Shape-validate an item reference token, returning it normalized.

    Accepts a project-local bare sequence or a self-describing ``PREFIX-seq``.
    Returns the stripped token, or ``None`` when it is syntactically not an
    item reference. Resolution to an internal id happens against the DB in
    :func:`_resolve_item_ref`.
    """
    from yoke_contracts.item_ref import parse_public_item_ref

    raw = raw.strip()
    if not raw:
        return None
    _, sequence = parse_public_item_ref(raw)
    if sequence is not None:
        return raw
    return None


def _resolve_item_ref(conn, raw: str) -> int | None:
    """Resolve a validated item-ref token to the internal ``items.id``.

    Bare strings resolve as project-local sequences; ``PREFIX-seq`` refs are
    self-describing. Returns ``None`` when the ref does not resolve.
    """
    from yoke_core.domain.project_identity_item_ref import resolve_cli_item_ref

    arg = str(raw).strip()
    return resolve_cli_item_ref(conn, arg)


def _parse_item_filters(
    args: list[str],
    *,
    allow_limit: bool = False,
) -> tuple[queries.ItemFilter, str, int | None] | int:
    """Parse common filter flags for item-list/item-count.

    Returns ``(ItemFilter, fields_csv, limit)`` on success, or an int exit code
    on error.
    """
    status = None
    priority = None
    workflow = None
    frozen: bool | None = None
    blocked: bool | None = None
    project = None
    fields = _QI_DEFAULT_FIELDS
    limit: int | None = None

    i = 0
    while i < len(args):
        if args[i] == "--status" and i + 1 < len(args):
            status = args[i + 1]
            i += 2
        elif args[i] == "--priority" and i + 1 < len(args):
            priority = args[i + 1]
            i += 2
        elif args[i] == "--workflow" and i + 1 < len(args):
            workflow = args[i + 1]
            i += 2
        elif args[i] in ("--frozen", "--blocked") and i + 1 < len(args):
            val = args[i + 1]
            if val in ("1", "true", "True"):
                _b = True
            elif val in ("0", "false", "False"):
                _b = False
            else:
                print(f"Error: {args[i]} must be 0 or 1", file=sys.stderr)
                return 2
            if args[i] == "--frozen":
                frozen = _b
            else:
                blocked = _b
            i += 2
        elif args[i] == "--project" and i + 1 < len(args):
            project = args[i + 1]
            i += 2
        elif args[i] == "--fields" and i + 1 < len(args):
            fields = args[i + 1]
            i += 2
        elif args[i] == "--limit" and i + 1 < len(args):
            if not allow_limit:
                print(f"Unknown argument: {args[i]}", file=sys.stderr)
                return 2
            try:
                limit = int(args[i + 1])
            except ValueError:
                print("Error: --limit must be a positive integer", file=sys.stderr)
                return 2
            if limit <= 0:
                print("Error: --limit must be a positive integer", file=sys.stderr)
                return 2
            i += 2
        else:
            print(f"Unknown argument: {args[i]}", file=sys.stderr)
            return 2

    filt = queries.ItemFilter(
        status=status,
        priority=priority,
        workflow=workflow,
        frozen=frozen,
        blocked=blocked,
        project=project,
    )
    return (filt, fields, limit)


def _validate_fields(fields_csv: str) -> list[str] | None:
    """Validate comma-separated field names against _QI_ALL_FIELDS.

    Returns the field list on success, None on validation failure (prints error).
    """
    field_list = [f.strip() for f in fields_csv.split(",")]
    for f in field_list:
        if f not in _QI_ALL_FIELDS:
            print(
                f"Error: unknown field '{f}'. Valid: {','.join(sorted(_QI_ALL_FIELDS))}",
                file=sys.stderr,
            )
            return None
    return field_list


__all__ = [
    "_QI_ALL_FIELDS",
    "_QI_VIRTUAL_FIELDS",
    "_QI_DEFAULT_FIELDS",
    "_QI_LARGE_TEXT_FIELDS",
    "_parse_item_id",
    "_parse_item_filters",
    "_validate_fields",
]
