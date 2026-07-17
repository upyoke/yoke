# Idea Phase: Function-Call Recipes (extracted)

Function-call recipe blocks used by `body-and-sync.md` and every other
wave-A skill (refine, feed, curate, amend, shepherd, plan, conduct,
simulate). The parent body-and-sync flow links here for the per-recipe
detail; the parent stays focused on prose discipline, decision
boundaries, and the canonical structured sequence of steps 8 through 11.

This is the canonical place every wave-A skill points readers when they
need the envelope shape or a concrete example for one of the function
ids registered through
`yoke_core.domain.handlers.__init_register__.register_all_handlers`.

## Function-call invocation envelope

Every Yoke mutation routes through one universal envelope. The
dispatcher lives at `POST /v1/functions/call` and is also callable
in-process via
`yoke_core.domain.yoke_function_dispatch.dispatch(FunctionCallRequest)`.
The envelope shape is identical for every function id:

```json
{
  "function": "<family>.<subfamily>.<operation>",
  "version": "v1",
  "actor": {"actor_id": "<session-or-operator>", "session_id": "<harness-session-id>"},
  "target": {"kind": "item", "item_id": 42},
  "payload": { ... family-specific ... },
  "preconditions": {},
  "options": {}
}
```

- `function` — id registered through
  `yoke_core.domain.handlers.__init_register__`. Validate with
  `validate_function_id(s)` from
  `yoke_contracts.api.function_call`.
- `actor` — harness sessions supply both `actor_id` and `session_id`;
  the dispatcher reads `session_id` for `claim_required_kind` checks.
- `target.kind` — discriminated union (`item`, `epic_task`, `section`,
  `claim`, `path_claim`, `qa_requirement`, `project_structure`,
  `global`, ...). See per-family recipes for the matching id fields.
- `payload` — typed Pydantic request model for the function id. The
  dispatcher returns `envelope_invalid` when malformed.
- `preconditions` / `options` — optional. Defaults to `{}`.

## Function-call response envelope

```json
{
  "success": true,
  "function": "items.structured_field.replace",
  "version": "v1",
  "result": { ... },
  "warnings": [],
  "error": null,
  "event_ids": ["<uuid>"]
}
```

- `success=false` carries `error.code` (`function_not_registered`,
  `envelope_invalid`, `claim_required`, `invalid_payload`, ...) plus an
  optional `recovery_hint`.
- `warnings` is the downstream-degraded surface (recovery hint names
  the follow-up function id).
- `event_ids` lists event-ledger rows the call emitted.

## Items: structured-field writes (`items.structured_field.*`)

Replace an entire structured field (`spec`, `design_spec`,
`technical_plan`, `worktree_plan`, `shepherd_log`, `shepherd_caveats`,
`test_results`, `deploy_log`, `browser_qa_metadata`):

```json
{
  "function": "items.structured_field.replace",
  "actor": {"actor_id": "idea-author", "session_id": "<session>"},
  "target": {"kind": "item", "item_id": 42},
  "payload": {"field": "spec", "content": "<full new content>", "source": "idea", "force": false}
}
```

Append a `## heading`-led addendum without rewriting the rest:

```json
{
  "function": "items.structured_field.append_addendum",
  "actor": {"actor_id": "refine-author", "session_id": "<session>"},
  "target": {"kind": "item", "item_id": 42},
  "payload": {"field": "spec", "heading": "Refinement notes", "content": "<addendum body>", "source": "refine"}
}
```

Despite the family name, `items.structured_field.section_upsert` and
`items.structured_field.section_append` operate on an `item_sections`
row (not inside a structured field column). `section_upsert` payload is
`{section, content, ordering?, source?}` and rewrites in place;
`section_append` payload is `{section, headline, content, ordering?,
source?}` and appends a timestamped headline-led entry. CLI exposes
`--section`, `--headline`, `--content`/`--content-file`/`--stdin`,
optional `--ordering`/`--source` — `--field` is NOT accepted.

## Items: section table (`items.section.*`)

For sections keyed by name on the `item_sections` table (for example,
`Progress Log`):

```json
{
  "function": "items.section.upsert",
  "actor": {"actor_id": "engineer", "session_id": "<session>"},
  "target": {"kind": "section", "item_id": 42, "section_name": "Progress Log"},
  "payload": {"content": "<full section body>", "ordering": 200, "source": "engineer"}
}
```

`items.section.delete` takes an empty payload (`{}`); `items.section.get`
is read-only and returns `{found, content, line_count}` in `result`.

## Items: progress log entry (`items.progress_log.append`)

Append a chronological entry to the `Progress Log` section. The handler
owns the ISO-8601 timestamp + headline header format:

```json
{
  "function": "items.progress_log.append",
  "actor": {"actor_id": "engineer", "session_id": "<session>"},
  "target": {"kind": "item", "item_id": 42},
  "payload": {"headline": "<one-line headline>", "content": "<body>", "source": "engineer"}
}
```

## Items: scalar field (`items.scalar.update`)

One mutation per call against any value in
`mutations.SUPPORTED_UPDATE_FIELDS`:

```json
{
  "function": "items.scalar.update",
  "actor": {"actor_id": "operator", "session_id": "<session>"},
  "target": {"kind": "item", "item_id": 42},
  "payload": {"field": "blocked", "value": 0}
}
```

## Lifecycle (`lifecycle.transition.execute`)

```json
{
  "function": "lifecycle.transition.execute",
  "actor": {"actor_id": "advance", "session_id": "<session>"},
  "target": {"kind": "item", "item_id": 42},
  "payload": {"target_status": "refined-idea", "source_status": "refining-idea"}
}
```

`source_status` is an optional precondition the handler verifies before
writing. The dispatcher routes through the canonical lifecycle gate so
structured-write checks (DB claim prose vs claim, File Budget vs path
claim, AC presence, etc.) all fire and the matching `ItemStatusChanged`
event is emitted.

## Workflow item: epic-task body and metadata (`workflow_item.epic_task.*`)

Replace an epic task body (function-call equivalent of the prior
`epic task-update-body` terminal recipe):

```json
{
  "function": "workflow_item.epic_task.body_replace",
  "actor": {"actor_id": "architect", "session_id": "<session>"},
  "target": {"kind": "epic_task", "epic_id": 1665, "task_num": 11},
  "payload": {"body": "<full new task body>"}
}
```

Other `workflow_item.epic_task.*` share the same target shape:
`.split` takes `{children: [...]}`; `.reassign` takes
`{new_worktree}`; `.add` takes
`{title, body, worktree, context_estimate, dependencies}`;
`.remove` takes `{reason}`; `.metadata_update` takes
`{fields: {...}}`.

## Workflow item: epic progress note (`workflow_item.epic_progress_note.append`)

```json
{
  "function": "workflow_item.epic_progress_note.append",
  "actor": {"actor_id": "engineer", "session_id": "<session>"},
  "target": {"kind": "epic_task", "epic_id": 1665, "task_num": 11},
  "payload": {"note_num": 3, "body": "<progress note body>", "commit_hash": "<sha>"}
}
```

## DB claim — unified amendment (`db_claim.amend`)

Routes both the `db_mutation_profile` and `db_compatibility_attestation`
columns through one atomic write. The `claim` dict is the unified payload
documented in `docs/db-reference/items-and-epics.md`.

```json
{
  "function": "db_claim.amend",
  "actor": {"actor_id": "refine", "session_id": "<session>"},
  "target": {"kind": "item", "item_id": 42},
  "payload": {
    "reason": "idea: spec/body declares no governed DB mutation",
    "claim": {"state": "none"}
  }
}
```

For declared payloads, populate the full `claim` dict (model name,
mutation intent, migration modules, `migration_strategy` when
`mutation_intent="apply"`, compatibility class, plus the four authored
attestation fields when `pre_merge_safe`). In
`pre_merge_readers_writers`, `role` is only `reader` or `writer`;
schema-changing migration modules use `writer`.

## Path claims (`claims.path.*`)

Register a new claim (function-call equivalent of the prior
`path-claims register` recipe):

```json
{
  "function": "claims.path.register",
  "actor": {"actor_id": "idea", "session_id": "<session>"},
  "target": {"kind": "item", "item_id": 42},
  "payload": {
    "item_id": 42,
    "paths": ["packages/yoke-core/src/yoke_core/domain/foo.py"],
    "mode": "exclusive",
    "allow_planned": false
  }
}
```

`integration_target` is optional. Omit it to default to the project's
trunk branch (resolved from `projects.default_branch`, falling back to
`main`); pass it explicitly only when gating against a non-trunk
branch.

`claims.path.widen` and the alias `claims.path.amend` take
`{claim_id, add_target_ids?, add_paths?, reason}`. `.release` takes
`{claim_id, reason}`. `.override` is last-resort and carries
`{path_claim_id, override_point, integration_target, actor_id, actor_reason}`.

## Work claims (`claims.work.*`)

```json
{
  "function": "claims.work.acquire",
  "actor": {"actor_id": "engineer", "session_id": "<session>"},
  "target": {"kind": "item", "item_id": 42},
  "payload": {"target": {"kind": "item", "item_id": 42}, "reason": "advance-implementation"}
}
```

`claims.work.release` takes `{claim_id, reason}` with
`target.kind="claim"`. `claims.work.holder_get` / `holder_list` are
read-only.

## Orchestration: board, packets, agents render

Board rebuild — function-call equivalent of the prior
`service_client backlog-cli rebuild-board` recipe:

```json
{
  "function": "board.rebuild.run",
  "actor": {"actor_id": "conduct", "session_id": "<session>"},
  "target": {"kind": "global"},
  "payload": {"force": false}
}
```

Substrate / packet drift checks (the dispatcher equivalents of the
prior `agents_render check` / `agents_render render` recipes):

```json
{
  "function": "agents.render.check",
  "actor": {"actor_id": "doctor", "session_id": "<session>"},
  "target": {"kind": "global"},
  "payload": {}
}
```

`agents.render.run` takes `{target_root?, dry_run}`. `packets.render.run`
takes `{role: "<role>_agent"}`; `packets.check.run` takes `{}` and
returns `{drift, seed_ok}`.

## Reads (no claim required)

```json
{
  "function": "items.get.run",
  "actor": {"actor_id": "any", "session_id": "<session>"},
  "target": {"kind": "item", "item_id": 42},
  "payload": {"fields": ["spec", "db_mutation_profile"]}
}
```

Empty `fields` returns the full canonical row. `epic_tasks.list.run`
takes `target={kind: "epic_task", epic_id: N}` with empty payload.
`events.query.run` takes `{event_name?, item_id?, since?, until?, limit?}`.
`path_claims.conflicts.list` takes `{integration_target?}`.
`doctor.run.run` takes `{only?, quick?, project?}`.
`projects.capability.has` takes `{project, cap_type}` on `target.kind="global"`.

## QA (`qa.*`)

```json
{
  "function": "qa.run.record_verdict",
  "actor": {"actor_id": "tester", "session_id": "<session>"},
  "target": {"kind": "qa_requirement", "qa_requirement_id": 17},
  "payload": {"executor_type": "agent", "qa_kind": "ac_verification", "verdict": "pass", "raw_result": "<evidence>"}
}
```

`qa.requirement.update` takes the matching `qa_requirement_id` target
plus a payload naming the field being updated.

## Retire-AC clause — topology-keyed (Bucket 1, `mutation_intent="apply"`)

When bucket 1 lands a declared payload with `mutation_intent="apply"`
and one or more `migration_modules`, the spec must carry an explicit
retire-the-module acceptance criterion whose timing matches the
project's install topology. The agent reads the topology and generates
the right clause automatically.

Read project + model name via `items.get.run` (`fields: ["project",
"db_mutation_profile"]`), resolve the `migration_model` capability
payload, then call `is_single_authoritative_install(model)` from
`yoke_core.domain.migration_install_topology` (one mapping arg).

Pick the matching template — append it to the spec's `Acceptance
Criteria` section through `items.structured_field.section_append`
(heading `Acceptance Criteria`):

- **Single-install**: `- [ ] AC-{N}: The one-shot migration module(s) ({modules}) and any module-only tests are deleted in the same slice as live-apply, once \`migration_audit.state='completed'\` is present on the model's authoritative DB.`
- **Multi-install**: `- [ ] AC-{N}: The one-shot migration module(s) ({modules}) and any module-only tests are deleted in the same commit range after \`migration_audit.state='completed'\` is present on every install of the model's authoritative DB.`

Where `{modules}` lists the slugs from
`db_mutation_profile.migration_modules`. If a retire-AC already exists
in the spec (operator hand-authored), verify it matches the topology
template; if not, replace via the section-append handler. Routing the
addendum through the structured-field section-append handler preserves
the rest of the spec body.
