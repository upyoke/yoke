---
slug: drop-subagent-dispatch-pending
retired-by: YOK-1880
migration-module: runtime/api/domain/migrations/drop_subagent_dispatch_pending.py
retired-without-apply: false
---

# Retirement decision — drop `subagent_dispatch_pending` table

## Why this exists

The `subagent_dispatch_pending` table was authored to record one row per Codex subagent dispatch so the dispatched child's first hook fire could atomically consume it and inherit the parent's `actor_id` + `execution_lane` via `parent_session_id`. The model assumed Codex `agent:` dispatch spawns each subagent as a separate thread carrying its own `thread_id` that becomes a fresh `YOKE_SESSION_ID`. The dispatch-rendering helper documented this assumption explicitly: *"Codex has no per-subagent env injection at the parent→child boundary."*

## Why it's being retired

Production behavior does not match the assumption. Empirical observation of in-flight `/yoke conduct YOK-1877` (Codex parent session `019e6a63-afc3-7d50-8ac7-28af66652ca9`) showed:

- `subagent_dispatch_pending` row count: **0**, despite multiple completed engineer and tester dispatches.
- `harness_sessions` lookup by parent_session_id: empty.
- Every subagent tool call (`git`, `python3 -m py_compile`, epic-progress-note appends) recorded under `session_id` equal to the parent's, with `cwd` equal to the parent's checkout.

Codex's `agent:` dispatch runs **in-process** inside the parent harness session — same `session_id`, same `cwd`, same hook chain. The auto-register hook in `runtime/harness/hook_runner/subagent_autoregister.py` was reachable but its match branch never fired because subagent threads share the parent's session id.

## Readers verified absent before drop

A repository-wide `git grep` against the live tree before this migration applied returned zero hits for:

- the literal table name `subagent_dispatch_pending` outside the drop migration + its test
- the writer `runtime.api.domain.dispatch_descriptors_codex_pending.write_pending_dispatch_row` (module deleted)
- the cleanup helper `runtime.api.domain.sessions_cleanup.expire_stale_pending_subagent_dispatch_rows` (removed in YOK-1880 commit `d1fc07bb1`)
- the autoregister hook entrypoint `runtime.harness.hook_runner.subagent_autoregister.auto_register_codex_subagent` (module deleted)
- the fresh-DB wiring `runtime.api.domain.schema_init_subagent_dispatch_tables.create_subagent_dispatch_pending_tables` (module deleted)
- the parity DDL `runtime.api.fixtures.schema_ddl_runtime_subagent._SUBAGENT_DISPATCH_DDL` (module deleted)

Every consumer was removed in the same slice as the drop migration's authoring.

## Apply timeline

- **2026-05-27** — drop migration authored and committed under YOK-1880.
- **TBD** — authoritative live apply against `data/yoke.db` via the governed-migration runner. Yoke is a single-authoritative-install project (`migration_install_topology.is_single_authoritative_install == True`), so the apply event lands a single `migration_audit` row with `state='completed'`.
- **Same slice as completed apply** — the migration module + its test (`runtime/api/domain/migrations/drop_subagent_dispatch_pending.py`, `runtime/api/domain/migrations/test_drop_subagent_dispatch_pending.py`) are deleted in the cutover commit per AC-14 of YOK-1880 and the doctrine in AGENTS.md `## Code Conventions` → "Delete completed migrations only after applied-everywhere evidence."

## What replaces it

Nothing. The audit attribution role the pending row would have served — "this subagent's tool call belongs to engineer dispatch X" — is replaced by the `actor_role` field on tool-call hook events. See `docs/event-catalog.md` and `docs/structured-logging-standard/agent-session-pattern.md`.

## Lesson

Future cross-harness reasoning should empirically verify the harness's actual subagent dispatch shape with real events before designing around an assumed shape. The dispatch-rendering helper's parenthetical "Codex has no per-subagent env injection at the parent→child boundary" was never empirically tested; one `SELECT COUNT(*) FROM subagent_dispatch_pending` against a live conduct would have caught the mismatch before the model accreted 47 files of dormant machinery.
