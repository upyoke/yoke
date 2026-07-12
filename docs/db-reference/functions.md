# Yoke Function Call Reference

The Yoke function-call surface is the **agent-facing** mutation surface for the Yoke control plane. Agents call typed function ids through one envelope shape; the dispatcher routes to a handler, verifies the calling session's claim, writes through the canonical domain owner, and emits structured events. Shell-quoted JSON payloads are not the operator path: the `python3 -m yoke_core.cli.db_router ...` and `python3 -m yoke_core.api.service_client ...` CLI commands remain as **retained operator/debug adapters** that build a typed `FunctionCallRequest` internally and dispatch through the same registry.

This file is the per-family function reference. The operator-readable Atlas (one row per `yoke` subcommand with function id + help status, plus the permanent / pending rosters and live promise-vs-live contradictions) lives at [`docs/atlas.md`](../atlas.md). Cross-link back from [db-reference.md](../db-reference.md) for the entry-point CLI, the domain catalog, and the structured-field discipline.

## Envelope

Every function call accepts and returns the same envelope shape, defined in `runtime/api/domain/yoke_function_models.py`:

```jsonc
// Request
{
  "function": "<family>.<subfamily>.<operation>",   // registered function id
  "version": 1,                                       // optional; defaults to current
  "request_id": "<uuid>",                             // dedup key; reusing returns the original response
  "actor": {                                          // who is calling
    "session_id": "<harness_sessions.session_id>",
    "actor_id": "<harness_sessions.actor_id>"
  },
  "target": {                                         // typed target ref; shape depends on function
    "kind": "item | epic_task | section | claim | process | none",
    "item_id": 1234,
    "epic_id": 833,
    "task_num": 5,
    "section_name": "Progress Log",
    "process_key": "...",
    "conflict_group": "..."
  },
  "payload": { /* function-specific typed body */ },
  "preconditions": { /* optional invariant assertions, e.g. allow_empty + reason */ },
  "options": { /* sync_github_body, rebuild_board, ... */ }
}

// Response
{
  "function": "...",
  "version": 1,
  "request_id": "...",
  "success": true,
  "result": { /* function-specific typed result */ },
  "warnings": [{"code": "...", "step": "..."}],
  "errors":   [{"code": "...", "message": "..."}],
  "event_ids": ["..."]
}
```

The dispatcher always emits `YokeFunctionCalled`. Repeated calls with the same `(function, request_id)` emit `DispatcherIdempotencyReplay` and return the cached response verbatim. The dedup store is the `function_call_ledger` table (exact `request_id` match, written alongside the emission; rows expire after the replay TTL via the events retention prune) — events stay telemetry; the ledger owns the replay decision. Partial-state failures (the primary write succeeded but a downstream sync degraded) return HTTP 207 with `success=true`, `warnings=[...]`, and a `DispatcherDownstreamDegraded` row in `events`. See [`docs/event-catalog.md`](../event-catalog.md) for the envelope schemas.

### Actor identity binding (transport-symmetric)

`actor.session_id` may be omitted: ambient identity resolves automatically — the env chain (`YOKE_SESSION_ID` → `CLAUDE_SESSION_ID` → `CODEX_THREAD_ID`) as the fast path, then the hook-written process-anchor registry (`yoke_core.domain.session_ambient_identity`). An explicit payload session always binds and is the flagged operator-debug override: when it diverges from the resolved ambient, dispatcher events carry `session_override: true` plus the divergent `ambient_session_id` in context. `actor_id` is never trusted from the payload — it resolves server-side from `harness_sessions` keyed on the bound session (a contradicting supplied value rejects with `actor_id_mismatch`), and over https the bearer-token actor overwrites it at the boundary. A mutating call with no session anywhere rejects with `actor_session_missing` — an infrastructure-bug signal (hook registration / anchor resolution failed), not a state agents should work around. Calls whose bound session has no `harness_sessions` row execute where downstream gates allow but are marked `provenance_unverified: true` in event context on both transports — unregistered-session writes are recorded, never silently trusted.

## Registry, schema, and dispatch endpoints

The FastAPI app exposes three routes mounted under `/v1/functions/`:

| Route | Purpose |
|---|---|
| `POST /v1/functions/call` | Dispatch a `FunctionCallRequest`; returns the typed `FunctionCallResponse`. |
| `GET  /v1/functions/registry` | Enumerate every registered function id (per family) plus metadata (`stability`, `target_kinds`, `claim_required_kind`, `adapter_status`). |
| `GET  /v1/functions/schema/{function_id}` | Return the JSON Schema for one function id's request body. |

The same registry is enumerable in-process via `yoke_core.domain.yoke_function_registry.list_entries()`.

**Compatibility surfaces.** `POST /v1/functions/call` and `GET /v1/health` are compatibility surfaces: clients and servers may run different engine versions, and both endpoints stay answerable across that skew. The server advertises its engine version in the health payload (`engine_version`, distinct from the constant API-contract `version`) and as an `X-Yoke-Engine-Version` response header on API responses; the CLI's https relay compares the header against the locally installed version and prints one advisory stderr warning per process on mismatch — it never blocks. Skew is expected mid-rollout; align the older side when behavior looks off.

## Claim verification matrix

Every registered function declares one of five `claim_required_kind` values; the dispatcher verifies before the handler runs.

| Value | When the dispatcher enforces |
|---|---|
| `None` | No claim verification. Reads, `claims.work.acquire`, and project-wide side effects (`board.rebuild`, `agents.render.run`). |
| `"item"` | Resolves the active work-claim row for `target.item_id` via `runtime.harness.harness_sessions.who_claims(item_id)`. The calling session's `session_id` must match. Otherwise `error.code="claim_required"` (HTTP 409). |
| `"epic"` | Same as `"item"` but resolves the parent epic id from `target.kind="epic_task"` (`target.epic_id`). |
| `"self_only"` | The claim itself is the target (e.g. `claims.work.release`). The handler reads the claim row by target and asserts `actor.session_id == row.session_id`. |
| `"operator_override"` | Requires the calling session to carry an operator-authored bypass marker (e.g. `path-claim-override`). Otherwise `error.code="operator_override_required"`. |

The five values are the closed enum; the registry rejects any other string at import time.

## Function families

The function id grammar is `<family>.<subfamily>.<operation>` validated by `yoke_contracts.api.function_call.validate_function_id`. Families today:

### `items.*` — structured field, section, and progress-log writes

Replaces every hand-authored `printf '%s' "$content" | python3 -m yoke_core.cli.db_router items update <id> <field> --stdin` / `item_field_transform` / `sections upsert` recipe.

| Function id | claim_required_kind | Handler | Result shape |
|---|---|---|---|
| `items.structured_field.replace` | `"item"` | `yoke_core.domain.handlers.items_structured_field` → `execute_structured_write` | `{old_lines, new_lines, verification_status}` |
| `items.structured_field.append_addendum` | `"item"` | same handler → `item_field_transform.append_addendum` | same shape |
| `items.structured_field.section_upsert` | `"item"` | same handler → `item_field_transform_sections.section_upsert` | same shape |
| `items.structured_field.section_append` | `"item"` | same handler → `item_field_transform_sections.section_append` | same shape |
| `items.section.upsert` | `"item"` | `yoke_core.domain.handlers.items_section` → `sections_cli.upsert` | `{section_name, content_lines}` |
| `items.section.delete` | `"item"` | same handler → `sections_cli.delete` | `{section_name, deleted}` |
| `items.section.get` (read) | `None` | same handler → `sections_cli.get` | `{section_name, content}` |
| `items.progress_log.append` | `"item"` | `yoke_core.domain.handlers.items_progress_log` | `{old_lines, new_lines, entry_count}` (read-then-upsert with `ordering=200`) |
| `items.scalar.update` | `"item"` | `yoke_core.domain.handlers.items_scalar` → `prepare_update` | `{field, old, new}` |
| `items.get` (read) | `None` | `yoke_core.domain.handlers.reads.items_get` | typed item payload (optional `fields[]`) |

**Canonical write — full-field replace:**

```jsonc
{
  "function": "items.structured_field.replace",
  "request_id": "<uuid>",
  "actor":  {"session_id": "...", "actor_id": "..."},
  "target": {"kind": "item", "item_id": 42},
  "payload": {"field": "spec", "content": "# Spec\n\n..."},
  "options": {"sync_github_body": true, "rebuild_board": true}
}
```

**Canonical write — additive transform (preserves prior content, appends a `## heading`-led block):**

```jsonc
{
  "function": "items.structured_field.append_addendum",
  "target":   {"kind": "item", "item_id": 42},
  "payload":  {
    "field":   "spec",
    "heading": "Refinement Addendum (2026-05-13)",
    "source":  "refine",
    "content": "..."
  }
}
```

The same handler accepts `items.structured_field.section_upsert` (replace a `## heading`-led block in place) and `items.structured_field.section_append` (append after the block). All variants preserve the empty/shrinkage/freeze guards on `execute_structured_write` and report old/new line counts plus a verification status.

**Canonical write — Progress Log entry:**

```jsonc
{
  "function": "items.progress_log.append",
  "target":   {"kind": "item", "item_id": 42},
  "payload":  {"headline": "kicked off engineer dispatch", "body": "..." }
}
```

The handler reads the existing `Progress Log` section, appends a timestamped entry, and upserts at `ordering=200` (the canonical Progress Log convention — see `AGENTS.md` § Progress Log).

### `workflow_item.epic_task.*` and `workflow_item.epic_progress_note.*` — epic-task amendment

Replaces every hand-authored `python3 -m yoke_core.domain.epic task-update-body <epic-id> <task-num>` / `task-upsert` / direct `epic_progress_notes` choreography in `/yoke amend` and related skills.

| Function id | claim_required_kind | Handler | Notes |
|---|---|---|---|
| `workflow_item.epic_task.body_replace` | `"epic"` | `yoke_core.domain.handlers.workflow_item_epic_task.body_replace` | Wraps `epic_task_crud.task_update_body`; returns `{old_lines, new_lines}`. |
| `workflow_item.epic_task.split` | `"epic"` | same handler → `epic_amend.task_split` | Preserves dependencies; renumbers downstream tasks atomically; returns `new_task_num`. |
| `workflow_item.epic_task.reassign` | `"epic"` | same handler → `epic_amend.task_reassign` | Updates the `worktree` column; returns `{old_worktree, new_worktree}`. |
| `workflow_item.epic_task.add` | `"epic"` | same handler → `epic_amend.task_add` | Typed payload (title, body, dependencies, …); writes via `task_upsert`. |
| `workflow_item.epic_task.remove` | `"epic"` | same handler → `epic_amend.task_remove` | Cascade-removes dependency edges. |
| `workflow_item.epic_task.metadata_update` | `"epic"` | same handler → `epic_amend.task_metadata_update` | Accepts `title`, `context_estimate`, `dependencies`, and other epic-task scalar fields. |
| `workflow_item.epic_task.review_seed` | `"epic"` | `yoke_core.domain.handlers.workflow_item_epic_task_review.handle_review_seed` | Wraps `epic.review_seed`; idempotent requirement seed; auto-advances `implementing → reviewing-implementation`. |
| `workflow_item.epic_task.review_insert` | `"epic"` | same module → `epic.review_insert` | Payload `{verdict: pass/fail (case-insensitive), body}`; a pass auto-advances `reviewing-implementation → reviewed-implementation`. |
| `workflow_item.epic_task.review_get` | `None` (read) | same module → `epic.review_get` | Most recent review as a pipe row (`id`, `epic_id`, `task_num`, `verdict`, `body`, `created_at`); `target_not_found` when none. |
| `workflow_item.epic_task.review_list` | `None` (read) | same module → `epic.review_list` | Review history newest-first; `{reviews, count}` where `count` is review ROWS (bodies are multi-line); empty list is success. |
| `workflow_item.epic_task.body_get` | `None` (read) | `yoke_core.domain.handlers.workflow_item_epic_task_state.handle_body_get` | Wraps `epic.task_get_body`; returns the body verbatim. |
| `workflow_item.epic_task.update_status` | `"epic"` | same module → `epic.task_update_status` | Non-pipeline status write + GitHub label sync; terminal success statuses refuse with `pipeline_required`. |
| `workflow_item.epic_task.simulation_upsert` | `"epic"` | same module → `epic.simulation_upsert` | Epic-level target (no `task_num`); payload `{phase, body}`; parses CLEAN / GAPS FOUND; replaces prior runs for the phase. |
| `workflow_item.epic_task.submission_receipt_get` | `None` (read) | same module → `epic.submission_receipt_get` | Payload `{after_note_count}`; returns the validated `PASS` receipt line; `receipt_invalid` on failing fields. |
| `workflow_item.epic_progress_note.append` | `"epic"` | `yoke_core.domain.handlers.workflow_item_epic_progress_note.append` | Wraps `yoke_core.domain.epic.progress_note_insert`. |

**Canonical write — epic task body replace:**

```jsonc
{
  "function": "workflow_item.epic_task.body_replace",
  "target":   {"kind": "epic_task", "epic_id": 833, "task_num": 5},
  "payload":  {"content": "..."}
}
```

**Canonical write — epic progress note:**

```jsonc
{
  "function": "workflow_item.epic_progress_note.append",
  "target":   {"kind": "epic_task", "epic_id": 833, "task_num": 5},
  "payload":  {"note_num": 3, "body": "..."}
}
```

### `lifecycle.*` — typed lifecycle transitions

| Function id | claim_required_kind | Handler |
|---|---|---|
| `lifecycle.transition` | `"item"` | `yoke_core.domain.handlers.items_scalar.lifecycle_transition` — routes through the same engines that `service_client advance/...` uses. |

```jsonc
{
  "function": "lifecycle.transition",
  "target":   {"kind": "item", "item_id": 42},
  "payload":  {"from_status": "implementing", "to_status": "reviewing-implementation", "reason": "..." }
}
```

### `claims.*` — work and path claim mutation

| Function id | claim_required_kind | Handler |
|---|---|---|
| `claims.work.acquire` | `None` (chicken-and-egg — handler asserts no active claim) | `yoke_core.domain.handlers.claims_work.acquire` |
| `claims.work.release` | `"self_only"` | `yoke_core.domain.handlers.claims_work.release` |
| `claims.path.register` | `"item"` | `yoke_core.domain.handlers.claims_path.register` (routes through `path_claims_resolve`) |
| `claims.path.widen` | `"item"` | same handler → `claims_path.widen` |
| `claims.path.release` | `"item"` | same handler → `claims_path.release` |
| `claims.path.amend` | `"item"` | same handler → `claims_path.amend` |
| `claims.path.override` | `"operator_override"` | same handler → existing path-claim override gate |
| `claims.coordination_lease.acquire` | `None` | `yoke_core.domain.handlers.claims_coordination_lease.acquire` |
| `claims.coordination_lease.heartbeat` | `"self_only"` | same handler |
| `claims.coordination_lease.release` | `"self_only"` | same handler |
| `claims.coordination_lease.list` | `None` (read) | same handler |
| `db_claim.amend` | `"item"` | `yoke_core.domain.handlers.db_claim.amend` — writes the `db_mutation_profile` and `db_compatibility_attestation` columns atomically through the unified payload described in [items-and-epics.md § DB Claim](items-and-epics.md). |

### `ephemeral_env.*` — ephemeral environment lifecycle updates

| Function id | claim_required_kind | Handler |
|---|---|---|
| `ephemeral_env.update` | `None` (project-role auth requires `items.write` on the environment row's project) | `yoke_core.domain.handlers.ephemeral_env` — updates one `ephemeral_environments` field by id via the authoritative `ephemeral_env.cmd_update` behavior. Terminal `status` values preserve the existing `stopped_at` auto-set. CLI adapter: `yoke ephemeral-env update ENV-ID FIELD VALUE`. Error codes: `payload_invalid`, `not_found`, `invalid_field`. |

### `qa.*`, `project_structure.*`, orchestration, reads

| Function id | claim_required_kind | Handler |
|---|---|---|
| `qa.requirement.update` / `qa.requirement.auto_create_for_item` | `"item"` | `yoke_core.domain.handlers.qa.*` |
| `qa.run.record_verdict` | `"item"` | `yoke_core.domain.handlers.qa_run` |
| `qa.browser_context.get` (read) | `None` | `yoke_core.domain.handlers.qa_browser` — one batched read for the browser-QA orchestrator: the item's unwaived `browser_smoke`/`browser_diff` requirements plus (with `expected_branch`) the latest `ephemeral_environments.deployed_sha`; echoes the resolved numeric `item_id` so ref-shaped callers learn it. CLI adapter: `yoke qa browser-context get`. |
| `qa.run.add` / `qa.run.complete` | `"item"` | `yoke_core.domain.handlers.qa_browser_writes` — the two-phase capture shape (`add` lands started/captured rows, `complete` finalizes in place); both verify the run belongs to the targeted requirement and emit `QARunStarted`/`QARunCaptured`/`QARunCompleted` by field presence. CLI adapters: `yoke qa run add` / `yoke qa run complete`. |
| `qa.artifact.add` | `"item"` | `yoke_core.domain.handlers.qa_browser_writes` — records one `qa_artifacts` row against a run. CLI adapter: `yoke qa artifact add`. |
| `qa.screenshot_evidence.pending_count` (read) / `qa.screenshot_evidence.satisfy` | `None` / `"item"` | `yoke_core.domain.handlers.qa_browser_evidence` — the advance gate's evidence pre-check and the inspection→`ac_verification` bridge (refuses with `capture_not_verified` until a capture run carries `verdict='pass'`). CLI adapters: `yoke qa screenshot-evidence pending-count` / `satisfy`. |
| Browser-QA orchestration | — | NOT a function id: the tool-shaped launcher token `yoke qa browser run` executes scenarios client-side (machine-local Playwright daemon) and consumes the four browser-QA ids above for every DB leg, so the flow works over both transports. |
| `qa.requirement.list` / `qa.requirement.get` / `qa.run.list` (reads) | `None` | `yoke_core.domain.handlers.qa_reads` — typed qa reads over the canonical column rosters (`qa_constants.REQ_COLUMNS` / `RUN_COLUMNS`; run rows include `execution_status`). `requirement.list` filters by item target (relay shape), payload `epic_id`, or payload `deployment_run_id`. CLI adapters: `yoke qa requirement list` / `yoke qa requirement get` / `yoke qa run list`. |
| `qa.gate_summary.run` (read) | `None` | `yoke_core.domain.handlers.qa_reads.handle_qa_gate_summary` — wraps `yoke_core.domain.qa_gate_summary.render_gate_summary` for an item or `epic_task` target with payload `transition` ∈ (`reviewed-implementation`, `implemented`); the dispatcher-backed replacement for the checkout-shaped `db_router qa gate-summary` agent leg. CLI adapter: `yoke qa gate-summary`. |
| `qa.requirement.add` / `qa.requirement.add_batch` | `"item"` | `yoke_core.domain.handlers.qa_requirement_create` — item-attached requirement creation mirroring `cmd_requirement_add`/`add_batch` (shared validators from `qa_requirement_policy_validation`, per-row `QARequirementCreated`). `add_batch` takes payload `rows` for the target item only (one claim verifies one batch); epic-task / deployment-run attachment stays on the operator-debug domain CLI. CLI adapters: `yoke qa requirement add` / `add-batch`. |
| `project_structure.patch.apply` | `"item"` | `yoke_core.domain.handlers.project_structure.patch_apply` |
| `board.rebuild` | `None` | `yoke_core.domain.handlers.orchestration.board_rebuild` |
| `board.data.get` (read) | `None` | `yoke_core.domain.handlers.orchestration.handle_board_data_get` — server half of the board rebuild: runs the board's full DB query plan (`yoke_core.board.data.collect_board_data`) for the payload's query-shaping inputs (`scope`, `config_values` from the client's `.yoke/board.json`, `zen_vision_count`, `repo_root_token`) and returns the recorded plan. The client (`yoke board rebuild` composition) renders markdown locally from this payload plus client-local inputs (board art, VISION entries, commit cache) and writes `.yoke/BOARD.md` itself, so board rebuilds work identically over https and in-process. CLI adapter: `yoke board data get`. |
| `packets.render` / `packets.check` | `None` | same |
| `agents.render.run` / `agents.render.check` | `None` | same (routes through `yoke_core.domain.agents_render`) |
| `doctor.run.run` (read) | `None` | `yoke_core.domain.handlers.reads_misc.handle_doctor_run` — machine Doctor surface: takes `{project, db_path, fix, only, quick, full}`, returns structured `{results[], scope, project, fail_count, warn_count, pass_count}`. Callers must pick exactly one scope (`quick`, `full`, or `only`); a JSON caller missing the scope flag receives `error.code="scope_required"`. Unknown HC slugs in `only` return `error.code="invalid_check"`. The retained human CLI is `yoke doctor run --json`, with byte-shape parity against this function. |
| `events.query` (read) | `None` | same |
| `items.get` (read) | `None` | same |
| `epic_tasks.list` (read) | `None` | same |
| `path_claims.conflicts.list` (read) | `None` | same |
| `checks.file_line.run` / `checks.idea_readiness.run` / `checks.path_claim_coverage.run` / `checks.schema_api_context.run` / `checks.agents_render.run` / `checks.event_registry.run` / `checks.migration_governance.run` | `None` | `yoke_core.domain.handlers.reads.*` |

## Adapter status

The CLI surfaces (`db_router items update`, `service_client db-claim-amend`, `item_field_transform`, `epic task-update-body`, etc.) remain **live** adapters — they construct a `FunctionCallRequest` internally and dispatch through the same registry. The adapter status (`live`, `deprecated`, `retired`, or `internal`) is recorded per registry entry and surfaced in [`docs/atlas.md`](../atlas.md). An `internal` function is a typed service-to-service boundary without a retained operator CLI adapter, so it is excluded from CLI-adapter parity. That adapter classification does not authorize access; the function's authorization scope and guardrails enforce who may dispatch it. Skill prose, packet prose, and agent docs reference the function id; operator/debug invocations of the CLI adapter remain valid and clearly labelled.

## Authoring conventions

- **Idempotency.** Always set `request_id` from a stable id (the calling agent's turn id, a hash of the (item, field, content), etc.). Replaying with the same `(function, request_id)` returns the cached response from `function_call_ledger` and emits `DispatcherIdempotencyReplay`; reusing a `request_id` across different function ids rejects with `idempotency_key_collision`. Ledger rows expire after the replay TTL (`function_call_ledger.LEDGER_TTL_DAYS`), after which the same `request_id` dispatches fresh.
- **Atomicity of mutation + side effect.** Functions that mutate state plus emit downstream events (sync GitHub body, rebuild board) wrap the side effect in `options`. Side-effect failures degrade to warnings via `DispatcherDownstreamDegraded`; the primary mutation either fully committed or fully rolled back.
- **Reads return typed payloads.** Function-call reads (`items.get`, `events.query`, `doctor.run.run`) return structured objects, not parseable terminal text. Agents that branch on read output should consume the typed fields, not regex the prior CLI's stdout.
- **Verification status.** Mutation handlers run a post-write re-read and report `verification_status`. Treat `verification_status="degraded"` as the same severity as a partial-state warning.

## Cross-links

- [`docs/event-catalog.md`](../event-catalog.md) — `YokeFunctionCalled`, `DispatcherIdempotencyReplay`, `DispatcherDownstreamDegraded` envelope schemas.
- [`docs/atlas.md`](../atlas.md) — operator-readable Atlas of the agent-facing surfaces.
- [items-and-epics.md § DB Claim — unified amendment workflow](items-and-epics.md) — the `db_claim.amend` payload shape.
- `runtime/api/domain/yoke_function_models.py` — Pydantic envelope models.
- `runtime/api/domain/yoke_function_dispatch.py` — dispatcher entry point.
- `runtime/api/domain/yoke_function_registry.py` — registry.
- `runtime/api/domain/handlers/__init_register__.py` — handler registration (idempotent).
