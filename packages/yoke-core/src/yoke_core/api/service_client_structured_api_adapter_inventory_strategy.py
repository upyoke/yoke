"""Strategy-family CLI adapter inventory rows."""

from __future__ import annotations

from yoke_core.api.service_client_structured_api_adapter_inventory_types import (
    AdapterEntry,
    read_entry as _read_entry,
)


STRATEGY_ADAPTERS = [
    _read_entry(function_id="strategy.doc.list", cli_invocation="yoke strategy doc list", notes="Per-project DB-authoritative strategy docs (slug, updated_at, bytes); .yoke/strategy/ is a rendered view."),
    _read_entry(function_id="strategy.doc.get", cli_invocation="yoke strategy doc get <slug>", notes="Prints one strategy doc's DB-authoritative content to stdout."),
    AdapterEntry(function_id="strategy.doc.create", cli_invocation="yoke strategy doc create <slug> --content-file PATH --target-root PATH", notes="Create a new DB-authoritative strategy doc, then render the gitignored local .yoke/strategy/ view into target_root."),
    AdapterEntry(function_id="strategy.doc.replace", cli_invocation="printf '%s' \"$CONTENT\" | yoke strategy doc replace <slug> --stdin --base-updated-at TS --target-root PATH", notes="Process-claim-gated CAS write (STRATEGIZE/FEED conflict group; base_updated_at from doc get); auto-renders the full strategy view into target_root; shrink guard bypass via --force."),
    AdapterEntry(function_id="strategy.doc.archive", cli_invocation="yoke strategy doc archive <slug> --target-root PATH", notes="Stamp archived_at on the strategy_docs row and re-render so the view relocates to .yoke/strategy/archive/<slug>.md; the doc stays a full editable row. Refused only while a foreign session holds the live STRATEGIZE/FEED process claim."),
    AdapterEntry(function_id="strategy.doc.unarchive", cli_invocation="yoke strategy doc unarchive <slug> --target-root PATH", notes="Clear archived_at and re-render so the view moves back to the active .yoke/strategy/<slug>.md location. Refused only while a foreign session holds the live STRATEGIZE/FEED process claim."),
    AdapterEntry(function_id="strategy.render.run", cli_invocation="yoke strategy render --target-root PATH", notes="Writes the project-scoped gitignored local .yoke/strategy/ rendered view from the DB authority (idempotent headers); target_root resolves client-side."),
    AdapterEntry(function_id="strategy.ingest.run", cli_invocation="yoke strategy ingest [SLUG ...] [--dry-run]", notes="CAS write-back of operator-edited rendered files on each header's base updated_at (lost-update protection); refuses headerless files; re-renders written docs."),
    AdapterEntry(function_id="strategy.seed_defaults.run", cli_invocation="yoke strategy seed-defaults [--project P]", notes="Cold-start the default placeholder corpus (MISSION/VISION/MASTER-PLAN/LANDSCAPE) for a project with zero strategy rows; idempotent — any existing row no-ops. The install bundle runs the same seeding server-side."),
]


__all__ = ["STRATEGY_ADAPTERS"]
