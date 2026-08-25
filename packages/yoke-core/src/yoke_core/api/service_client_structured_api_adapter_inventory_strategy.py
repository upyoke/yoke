"""Strategy-family CLI adapter inventory rows."""

from __future__ import annotations

from yoke_core.api.service_client_structured_api_adapter_inventory_types import (
    AdapterEntry,
    read_entry as _read_entry,
)


STRATEGY_ADAPTERS = [
    _read_entry(
        function_id="strategy.surface.list",
        cli_invocation="yoke strategy surface list --project P",
    ),
    _read_entry(
        function_id="strategy.surface.get",
        cli_invocation="yoke strategy surface get SLUG --project P",
    ),
    _read_entry(
        function_id="strategy.revision.diff",
        cli_invocation=(
            "yoke strategy revision diff SLUG --from-revision N "
            "--to-revision N --project P"
        ),
    ),
    AdapterEntry(
        function_id="strategy.revision.restore",
        cli_invocation=(
            "yoke strategy revision restore SLUG --revision N "
            "--base-updated-at TS --project P"
        ),
    ),
    AdapterEntry(
        function_id="strategy.parent.set",
        cli_invocation=(
            "yoke strategy parent set SLUG --parent-slug PARENT --project P"
        ),
    ),
    AdapterEntry(
        function_id="strategy.coordination.append",
        cli_invocation=(
            "yoke strategy coordination append SLUG --section NAME "
            "--entry TEXT --project P"
        ),
    ),
    _read_entry(
        function_id="strategy.execution.get",
        cli_invocation="yoke strategy execution get ITEM --project P",
    ),
    AdapterEntry(
        function_id="strategy.execution.link",
        cli_invocation=(
            "yoke strategy execution link ITEM --slug SLUG --project P"
        ),
    ),
    AdapterEntry(
        function_id="strategy.claim.acquire",
        cli_invocation="yoke strategy claim acquire ITEM --project P",
    ),
    AdapterEntry(
        function_id="strategy.claim.release",
        cli_invocation=(
            "yoke strategy claim release (ITEM | PROCESS_KEY) "
            "[--reason TEXT] --project P"
        ),
    ),
    AdapterEntry(
        function_id="strategy.doc_claim.acquire",
        cli_invocation=(
            "yoke strategy doc-claim acquire SLUG [--reason TEXT] --project P"
        ),
    ),
    AdapterEntry(
        function_id="strategy.doc_claim.release",
        cli_invocation=(
            "yoke strategy doc-claim release SLUG [--reason TEXT] --project P"
        ),
    ),
    _read_entry(
        function_id="strategy.doc_claim.list",
        cli_invocation="yoke strategy doc-claim list [--all] --project P",
    ),
    AdapterEntry(
        function_id="strategy.claim.break_glass_release",
        cli_invocation=(
            "yoke strategy claim break-glass-release ITEM "
            "--reason TEXT --project P"
        ),
    ),
    _read_entry(
        function_id="strategy.doc.list",
        cli_invocation="yoke strategy doc list",
        notes="Per-project DB-authoritative strategy docs (slug, title, status metadata, updated_at, bytes); .yoke/strategy/ is a rendered view.",
    ),
    _read_entry(
        function_id="strategy.doc.get",
        cli_invocation="yoke strategy doc get <slug>",
        notes="Prints one strategy doc's DB-authoritative content to stdout.",
    ),
    AdapterEntry(
        function_id="strategy.doc.create",
        cli_invocation="yoke strategy doc create <slug> --content-file PATH --target-root PATH",
        notes="Create a new DB-authoritative strategy doc, then render the gitignored local .yoke/strategy/ view into target_root.",
    ),
    AdapterEntry(
        function_id="strategy.doc.replace",
        cli_invocation="printf '%s' \"$CONTENT\" | yoke strategy doc replace <slug> --stdin --base-updated-at TS --target-root PATH",
        notes="Process-claim-gated CAS write (STRATEGIZE/FEED conflict group; base_updated_at from doc get); auto-renders the full strategy view into target_root; shrink guard bypass via --force.",
    ),
    AdapterEntry(
        function_id="strategy.doc.archive",
        cli_invocation="yoke strategy doc archive <slug> --target-root PATH",
        notes="Stamp archived_at on the strategy_docs row and re-render so the view relocates to .yoke/strategy/archive/<slug>.md; the doc stays a full editable row. Refused only while a foreign session holds the live STRATEGIZE/FEED process claim.",
    ),
    AdapterEntry(
        function_id="strategy.doc.unarchive",
        cli_invocation="yoke strategy doc unarchive <slug> --target-root PATH",
        notes="Clear archived_at and re-render so the view moves back to the active .yoke/strategy/<slug>.md location. Refused only while a foreign session holds the live STRATEGIZE/FEED process claim.",
    ),
    AdapterEntry(
        function_id="strategy.render.run",
        cli_invocation="yoke strategy render --target-root PATH",
        notes="Writes the project-scoped gitignored local .yoke/strategy/ rendered view from the DB authority (idempotent headers); target_root resolves client-side.",
    ),
    AdapterEntry(
        function_id="strategy.ingest.run",
        cli_invocation=(
            "yoke strategy ingest [SLUG ...] [--content-file PATH] [--dry-run]"
        ),
        notes="CAS write-back of operator-edited rendered files on each header's base updated_at (lost-update protection); --content-file accepts one rendered handoff from a readable path; receipts carry the proposed content SHA-256; refuses headerless files; re-renders written docs.",
    ),
    AdapterEntry(
        function_id="strategy.seed_defaults.run",
        cli_invocation="yoke strategy seed-defaults [--project P]",
        notes="Top up the default placeholder corpus (MISSION/VISION/MASTER-PLAN/LANDSCAPE/CURRENT-PLAN): each missing default slug gains its placeholder, existing rows are never touched — the healer for projects predating a roster addition. The install bundle runs the same seeding server-side.",
    ),
]


__all__ = ["STRATEGY_ADAPTERS"]
