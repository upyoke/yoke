"""Item-family entries for the structured API adapter inventory."""

from __future__ import annotations

from yoke_core.api.service_client_structured_api_adapter_inventory_types import (
    AdapterEntry,
    read_entry,
)


ITEMS_ADAPTERS = [
    read_entry(
        function_id="items.overview.list",
        cli_invocation="yoke items overview list --project P",
    ),
    read_entry(
        function_id="items.detail.get",
        cli_invocation="yoke items detail get ITEM --project P",
    ),
    read_entry(
        function_id="items.public_ref.lookup",
        cli_invocation="yoke items public-ref lookup --id N [--id N ...]",
    ),
    AdapterEntry(
        function_id="item_worktrees.create",
        cli_invocation=(
            "yoke item-worktrees create <PREFIX-N> "
            "[--lane-role worker|integration --branch BRANCH] "
            "[--project P] [--session-id S] [--json]"
        ),
        notes=(
            "Ensure the sole policy-required default lane, or register one "
            "explicit policy-allowed additional lane."
        ),
    ),
    read_entry(
        function_id="item_worktrees.list",
        cli_invocation=(
            "yoke item-worktrees list <PREFIX-N> "
            "[--project P] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="item_worktrees.path_record",
        cli_invocation=(
            "yoke item-worktrees path-record <PREFIX-N> --worktree-id ID "
            "--branch BRANCH --path ABSOLUTE_PATH "
            "[--project P] [--session-id S] [--json]"
        ),
        notes=(
            "Record a materialized local path with active-lane id and "
            "unchanged-branch preconditions."
        ),
    ),
    read_entry(
        function_id="item_worktrees.get",
        cli_invocation=(
            "yoke item-worktrees get <PREFIX-N> [--lane-role ROLE] "
            "[--field branch|path|lane-role|state|id] "
            "[--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="item_worktrees.release",
        cli_invocation=(
            "yoke item-worktrees release <PREFIX-N> --all-active "
            "--reason evidence-only-recovery [--session-id S] [--json]"
        ),
        notes="Guarded release of one attested clean evidence-only lane.",
    ),
    AdapterEntry(
        function_id="items.create",
        cli_invocation=(
            "yoke items create TITLE WORKFLOW --entry-surface harness_skill "
            "--project P --execution-instructions-considered"
        ),
        notes=(
            "Workflow-selected creation through a registered entry surface. "
            "Every non-web surface attests the operator "
            "execution-instruction read with "
            "--execution-instructions-considered."
        ),
        canonical_skill_invocation=(
            'yoke items create "{title}" {workflow} '
            '--entry-surface harness_skill --project "${_project}" '
            '--execution-instructions-considered'
        ),
    ),
    AdapterEntry(
        function_id="items.structured_field.replace",
        cli_invocation=(
            "python3 -m yoke_core.cli.db_router items update YOK-N "
            "<field> --stdin | --body-file PATH"
        ),
        notes="structured-field write via stdin/body-file",
    ),
    AdapterEntry(
        function_id="items.structured_field.append_addendum",
        cli_invocation=(
            "python3 -m yoke_core.domain.item_field_transform append-addendum"
        ),
        notes="additive heading addendum",
    ),
    AdapterEntry(
        function_id="items.structured_field.section_upsert",
        cli_invocation=(
            "python3 -m yoke_core.domain.item_field_transform section-upsert"
        ),
    ),
    AdapterEntry(
        function_id="items.structured_field.section_append",
        cli_invocation=(
            "python3 -m yoke_core.domain.item_field_transform section-append"
        ),
    ),
    AdapterEntry(
        function_id="items.section.upsert",
        cli_invocation="python3 -m yoke_core.cli.db_router sections upsert",
    ),
    read_entry(
        function_id="items.section.get",
        cli_invocation="python3 -m yoke_core.cli.db_router sections get",
    ),
    AdapterEntry(
        function_id="items.section.delete",
        cli_invocation="python3 -m yoke_core.cli.db_router sections delete",
    ),
    AdapterEntry(
        function_id="items.progress_log.append",
        cli_invocation=(
            "python3 -m yoke_core.cli.db_router sections upsert "
            "YOK-N 'Progress Log' --content-file PATH"
        ),
    ),
    AdapterEntry(
        function_id="items.scalar.update",
        cli_invocation=(
            "python3 -m yoke_core.cli.db_router items update YOK-N <field> <value>"
        ),
    ),
    AdapterEntry(
        function_id="items.freeze.run",
        cli_invocation="yoke items freeze YOK-N",
        notes="Takes the item claim for the caller; refuses a foreign holder.",
    ),
    AdapterEntry(
        function_id="items.thaw.run",
        cli_invocation="yoke items thaw YOK-N",
        notes="Takes the item claim for the caller; refuses a foreign holder.",
    ),
    AdapterEntry(
        function_id="items.cancel.run",
        cli_invocation="yoke items cancel YOK-N --reason TEXT [--ref PREFIX-M]",
        notes=(
            "Takes the item claim for the caller; refuses a foreign holder. "
            "Consumes execute_close (dependency reconciliation + GitHub close). "
            "Frozen items cancel in one step; frozen is cleared as part of the "
            "terminal close, not thawed for later."
        ),
    ),
    AdapterEntry(
        function_id="items.block.run",
        cli_invocation="yoke items block YOK-N --reason TEXT",
        notes=(
            "Takes the item claim for the caller; refuses a foreign holder. "
            "Writes blocked_reason before blocked so the flag is the only "
            "observable commit point."
        ),
    ),
    AdapterEntry(
        function_id="items.unblock.run",
        cli_invocation="yoke items unblock YOK-N",
        notes="Takes the item claim for the caller; refuses a foreign holder.",
    ),
    AdapterEntry(
        function_id="items.merge_provenance.operator_correct",
        cli_invocation=(
            "yoke items merge-provenance operator-correct YOK-N "
            "--merged-at YYYY-MM-DDTHH:MM:SSZ --reason TEXT"
        ),
        notes=(
            "Human-only repair for a terminal item whose merged_at was never "
            "recorded. Refuses a hook context, a non-terminal item, an "
            "already-set merged_at, and a future timestamp. A live item "
            "records its merge through yoke merge item YOK-N instead."
        ),
    ),
    AdapterEntry(
        function_id="items.github_sync",
        cli_invocation="yoke items github-sync YOK-N",
        notes=(
            "Backlog GitHub item/epic sync; registered agent surface is "
            "yoke items github-sync YOK-N."
        ),
    ),
]


__all__ = ["ITEMS_ADAPTERS"]
