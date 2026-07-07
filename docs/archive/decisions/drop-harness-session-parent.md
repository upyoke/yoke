---
slug: drop-harness-session-parent
retired-by: YOK-1880
migration-module: runtime/api/domain/migrations/drop_harness_session_parent.py
retired-without-apply: false
---

# Retirement decision — drop `harness_sessions.parent_session_id` + index

## Why this exists

The `harness_sessions.parent_session_id` column and its companion index `idx_harness_sessions_parent` were authored as the structural anchor of the Codex parent→child identity-propagation model. The column was set when a child subagent session was auto-registered after consuming a `subagent_dispatch_pending` row, and four caller sites then walked one hop through `sessions_parent_cascade.resolve_one_deep_parent` to inherit the parent's claims and actor identity:

- `runtime.api.domain.path_claim_active_claim_lookup.resolve_active_claim_for_session`
- `runtime.api.domain.session_claimed_worktrees.claimed_worktrees`
- `runtime.api.domain.yoke_function_actor_identity._default_actor_id_resolver`
- `runtime.api.domain.yoke_function_dispatch_claims._resolve_authority_session`
- (plus `yoke_function_dispatch_events.emit_called` added an `effective_session_id` envelope field when the column was non-NULL)

## Why it's being retired

The column was never populated in production. Codex `agent:` dispatch runs in-process inside the parent harness session, so the parent's `session_id` is the subagent's `session_id` and no per-subagent identity-propagation layer is needed. Yoke's existing claim-aware lookups land on the parent's row directly; the cascade fallbacks never fired. The companion table `subagent_dispatch_pending` is retired in the sibling decision record [`drop-subagent-dispatch-pending.md`](drop-subagent-dispatch-pending.md), where the production-behavior evidence is documented in full.

## Readers verified absent before drop

A repository-wide `git grep` against the live tree before this migration applied returned zero hits for:

- the column reference `harness_sessions.parent_session_id` outside the drop migration + its test
- the resolver `runtime.api.domain.sessions_parent_cascade.resolve_one_deep_parent` and the sibling `parent_session_id_for` (module deleted)
- the cascade-fallback call sites in `path_claim_active_claim_lookup.resolve_active_claim_for_session`, `session_claimed_worktrees.claimed_worktrees`, `yoke_function_actor_identity._default_actor_id_resolver`, `yoke_function_dispatch_claims.verify_claim` (collapsed to direct-equality lookups)
- the envelope field `effective_session_id` on `YokeFunctionCalled` (`yoke_function_dispatch_events.emit_called` no longer populates it)
- the `parent_session_id` insert path on `sessions_lifecycle_registry.register_session` (parameter removed)
- the index name `idx_harness_sessions_parent` outside the drop migration

Five test files that previously seeded the column for cascade-specific assertions were either deleted (cascade-only tests) or trimmed to drop the column from their DDL fixtures (`test_claims_work_release_session_scoped`, `test_lint_session_cwd_parallel_fanout`, `test_sessions_lifecycle_destructive_guard_defer_refresh`).

The carve-out: five unrelated helpers under `runtime/api/domain/advance_skip_finalize.py`, `runtime/api/domain/conduct_reviewed_handoff.py`, `runtime/api/service_client_work_claims.py`, `runtime/api/service_client_work_claims_identity.py`, and its test use `effective_session_id` as a local variable / dataclass field for session-resolver bookkeeping. That usage is semantically unrelated to the dropped envelope field; YOK-1880 AC-5 explicitly carves it out.

## Apply timeline

- **2026-05-27** — drop migration authored and committed under YOK-1880.
- **TBD** — authoritative live apply against `data/yoke.db` via the governed-migration runner. Yoke is a single-authoritative-install project, so the apply event lands a single `migration_audit` row with `state='completed'`.
- **Same slice as completed apply** — the migration module + its test (`runtime/api/domain/migrations/drop_harness_session_parent.py`, `runtime/api/domain/migrations/test_drop_harness_session_parent.py`) are deleted in the cutover commit per AC-14 of YOK-1880.

## Migration shape

`ALTER TABLE harness_sessions DROP COLUMN parent_session_id` is supported natively by SQLite ≥ 3.35.0; the governed runner targets ≥ 3.39 so no table-rebuild dance is required. The index `idx_harness_sessions_parent` is dropped explicitly before the column drop as defense in depth on engines that don't cascade index removal automatically.

## What replaces it

Nothing. Subagent audit attribution within the parent session flows through the `actor_role` field on tool-call hook events (see `docs/event-catalog.md`).
