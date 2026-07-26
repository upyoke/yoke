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
    AdapterEntry(
        function_id="items.create",
        cli_invocation=(
            "yoke items create TITLE WORKFLOW "
            "--entry-surface harness_skill --project P"
        ),
        notes="Workflow-selected creation through a registered entry surface.",
        canonical_skill_invocation=(
            "yoke items create \"{title}\" {workflow} "
            "--entry-surface harness_skill --project \"${_project}\""
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
            "python3 -m yoke_core.cli.db_router items update YOK-N "
            "<field> <value>"
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
