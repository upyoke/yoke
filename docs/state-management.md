# State Management

All authoritative Yoke state lives in the configured Postgres authority. Compacting, restarting, crashing, or switching tabs never loses state.

## Work Item Registry

Every work item gets a stable global integer `items.id`. Its user-facing
reference combines the owning project's `public_item_prefix` with the item's
per-project `project_sequence` (for example, `YOK-42`). Both identities persist
through the item's entire lifecycle. The registry is the single source of
truth for every registered workflow and immutable workflow-version pin.

### ID System

- **Public format:** `<PREFIX>-N` (for example, `YOK-42`) — the prefix comes
  from `projects.public_item_prefix`.
- **Scope:** `items.id` is globally unique in the universe;
  `items.project_sequence` is monotonically allocated within one project.
- **Counters:** the registry assigns the global integer id and the next
  project sequence; `UNIQUE(project_id, project_sequence)` preserves the
  project-local namespace.
- **Stability:** neither identity changes. A GitHub issue number is separate
  metadata in `github_issue`.
- **Generated tasks** stored in `epic_tasks` keep plan-order numbering
  (001, 002) — internal to their parent item, not global YOK-N IDs.

### Workflows

Every item stores `workflow_id` and `workflow_version_id`. Its pinned immutable
definition is the authority for:

- ordered `stages`, `transitions`, and `terminal_stage_ids`;
- gates referenced by each target stage;
- allowed `entry_surfaces`;
- `skill_bindings`, interpreted as half-open
  `from_stage_id <= current_stage < through_stage_id` intervals; and
- policies for artifacts, worktrees, generated children, parallelism, path
  claims, approvals, and delivery.

Do not infer a lifecycle or an item type from the workflow id.
Selecting a different current version affects future items only; moving an
existing item is explicit and compatibility-checked. See
[workflows.md](workflows.md).

Current definitions with `policies.delivery=release_stage` bind `usher` across
their delivery tail and may use deployment runs. Definitions with
`continuous_slice_actions` or `after_merge_action` use different delivery
semantics and do not inherit that tail. Two deployment-run halt states
(`needs-capability`, `awaiting-approval`) may interrupt a run. They are not
item stages.

### Status Vocabulary

An item's `status` is its current stage id. The same id may appear in several
definitions, but its order, target-stage gates, and skill owner are always
read from the item's exact pin. A stage name alone never selects a command.

The runtime also recognizes the engine-exceptional ids `cancelled`, `stopped`,
`blocked`, and `failed`. Operational item blocking uses the orthogonal
`blocked` / `blocked_reason` fields and preserves the pinned stage; the
exceptional `blocked` id remains an engine compatibility state. The
`epic_tasks` table has its own canonical status vocabulary below, including
task-level `blocked`.

**Note:** `needs-capability` and `awaiting-approval` are **halt states** on the
deployment run, not item statuses. In a compatible `release_stage` workflow,
the item remains at its pinned delivery stage while halted. The
`current_stage` field on the `deployment_runs` row tracks position within the
deployment pipeline. See Delivery Lifecycle below for details.

### Item Fields

Items are read via `yoke items get YOK-N <field>`. The `body` field is a virtual rendered field assembled on demand from structured fields — it is not stored in the DB.

**Fields:**
- `id` — stable global integer primary key
- public reference — derived from the owning project's
  `public_item_prefix` plus `project_sequence`; it is not a second primary key
- `title` — human-readable title
- `project_id` — integer project authority
- `project_sequence` — stable sequence within that project
- `workflow_id` — stable workflow-registry identity; it is not an item type
- `workflow_version_id` — immutable definition version pinned at creation
- `status` — current stage id, validated against the pinned version
- `priority` — `high`, `medium`, or `low`
- `github_issue` — GitHub issue reference, populated on sync (null if unsynced)
- `created_at` — ISO timestamp, set on creation
- `updated_at` — ISO timestamp, updated on every field change
- `merged_at` — ISO timestamp, automatically populated by `yoke_core.engines.done_transition` when the item transitions to `done` (set to current UTC timestamp if null). Not overwritten if already set (e.g., by the merge pipeline). Tracks when the item's code was finalized on main.

**Item-level dependencies** are stored in the `item_dependencies` table (not as an item field). Every row is a canonical blocker with `gate_point` (`activation`, `integration`, or `closure`) and `satisfaction` (`status:done`, `status:implemented`, or `fact:merged`). Each row carries a `rationale` (human-readable) and `evidence_json` (structured provenance). A shared dependency-planning kernel (`dependency_planning.py`) evaluates gates and plans candidate sets for all consumers. Transition and dispatch gates call the hard-block gate or the dependency-planning service commands. See `.yoke/docs/reference/db-reference.md` for the full schema.

### Counter Mechanics

When the backlog create path inserts an item:
1. Resolve `project_id` and allocate the next `project_sequence` for it.
2. Insert the row and receive its global integer `items.id`.
3. Format the public reference from the project's prefix and sequence.
4. Make the item accessible through `yoke items get <PREFIX-N> body`.
5. Trigger board rebuild.

The counters never decrement. Removed items leave gaps; identities are never
reused.

## Backlog Item Lifecycle

Every ordinary transition is interpreted against the item's exact immutable
pin:

1. Load `workflow_id` and `workflow_version_id` from the item.
2. Load that version and validate the requested source and target against its
   ordered `transitions`.
3. Evaluate the gate references attached to the target stage.
4. Resolve the current owner from the one active `skill_bindings` interval.
5. Apply definition policies for artifacts, claims, lanes, generated
   children, approvals, and delivery.

Use `yoke workflows item get YOK-N` and then
`yoke workflows version get WORKFLOW VERSION` when diagnosing a live item.
Publishing a new preferred version does not alter the in-flight pin.

For a compatible `release_stage` definition, the registered delivery skill
may create a deployment run. Each run references a `deployment_flow`.
Item-bound runs operate on one or more items through
`deployment_run_items`; environment-level runs may intentionally operate on
zero items. Run execution may move the item through the definition's delivery
stages, while `needs-capability` and `awaiting-approval` remain run halt states.
Stage authority for the run itself lives on `deployment_runs.current_stage`.
See `.yoke/docs/reference/db-reference.md` for the `deployment_runs`,
`deployment_run_items`, `deployment_run_qa`, `deployment_flows`, `sites`,
`environments`, and `project_capabilities` table schemas.

Specs, plans, and review artifacts live in structured item fields (`spec`, `technical_plan`, `worktree_plan`, `shepherd_log`, `test_results`, etc.). `items.body` is a virtual rendered field assembled on demand from these structured fields — not stored in the DB, not a write target.

## Delivery Lifecycle

Delivery behavior is policy-owned. A definition with
`policies.delivery=release_stage` may bind `usher` across an
`implemented → release → done` tail and use deployment runs. A definition
with `continuous_slice_actions` or `after_merge_action` keeps delivery inside
its registered direct skill instead.

### Release-stage skill boundary

For a current compatible definition, the `usher` binding begins at
`implemented` and owns the delivery tail exclusively. Earlier implementation
and finishing work belongs to whichever bindings cover those stages; shared
stage ids do not imply `advance`, `conduct`, or `polish`.

The `through_stage_id` of every binding is a fresh command and claim handoff.
The previous skill releases its claim at the boundary, and the next
registered skill starts through its own entrypoint. For a `release_stage`
tail, `/yoke usher YOK-N` manages merge, deployment, verification, and the
terminal transition. Operators still control merge ordering, batching, and
deployment timing.

Definitions without an `usher` binding do not enter this boundary and do not
inherit its `release` stage or no-flow shortcut.

### Delivery Pipeline Internals

Run mechanics, halt states, step runner types, and ephemeral environments live in [state-management/delivery-internals.md](state-management/delivery-internals.md):

- **Deployment runs** — stage authority on the run row, item lifecycle during a run, `deploy_stage` cache.
- **Halt states** — `needs-capability`, `awaiting-approval`, GitHub-protection-rule integration.
- **Capability self-invention** — exit-code-2 protocol, template registration, operator resume.
- **Human approval gate** — `/yoke approve` flow.
- **Step runner dispatch** — `auto`, `script`, `health-check`, `human-approval`, `github-actions-workflow`.
- **Usher state machine** — full state diagram.
- **No-flow fast path** — the `implemented → done` shortcut for a compatible
  `release_stage` definition.
- **Ephemeral environments** — implementation-skill preview environments
  tracked in `ephemeral_environments` when the pinned policies enable them.

## Epic Task State (DB table: `epic_tasks`)

One row per task. Created by `yoke_core.api.service_client_items`. Updated by `yoke_core.domain.update_status`.

**Columns:**

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Auto-increment primary key |
| `epic_id` | INTEGER | Numeric parent item ID |
| `task_num` | INTEGER | Plan-order number (e.g., 1, 2, 3) |
| `title` | TEXT | Task title |
| `item_worktree_id` | INTEGER | Universal lane record in `item_worktrees` |
| `context_estimate` | TEXT | Size estimate (e.g., "S", "30k") |
| `dependencies` | TEXT | Comma-separated prerequisite task numbers within the same epic |
| `status` | TEXT | Current lifecycle status |
| `dispatch_attempts` | INTEGER | Auto-incremented on each `implementing` transition |
| `body` | TEXT | Task body |
| `github_issue` | TEXT | GitHub issue reference (e.g., "#42") |
| `blocked_by` | TEXT | Current task-level blocker context |
| `max_attempts` | INTEGER | Retry limit (default 5) |
| `agent_id` | TEXT | Active task agent identity |
| `last_heartbeat` | TEXT | Latest task-agent heartbeat |
| `last_activity_at` | TEXT | Latest task activity timestamp |

**History:** Status transitions are logged in the `events` table as `task_status_change` rows. Epic task context lives on `item_id`/`task_num`; `from_status`, `to_status`, and `note` live in the JSON envelope.

## Epic Task Status Flow

```
planning → plan-drafted → refining-plan → planned → implementing → reviewing-implementation
 → reviewed-implementation → polishing-implementation → implemented → release → done
Plus: failed, blocked, stopped
```

- `planned` → `implementing`: dispatch starts, `dispatch_attempts` incremented
- `implementing` → `reviewing-implementation`: engineering work is ready for review
- `reviewing-implementation` → `reviewed-implementation`: review passes
- `reviewed-implementation` → `polishing-implementation`: task polish starts
- `polishing-implementation` → `implemented`: task polish completes
- `implemented` → `release`: task enters the parent release/deployment phase when applicable
- `release` / `implemented` → `done`: done-transition cascade when the parent epic reaches done
- `reviewing-implementation` → `failed`: review fails and retry budget is exhausted
- `implementing` → `stopped`: session crash or `/yoke stop`
- `blocked`: cross-worktree dependency unmet during auto-chain
- Auto-unblock: when a task completes, `yoke_core.domain.update_status` scans blocked tasks in the same epic and unblocks those whose deps are all met
- Auto-promote: when an epic transitions to `done`, `yoke_core.engines.done_transition` Step 6b promotes any remaining terminal-success tasks (`reviewed-implementation`, `polishing-implementation`, `implemented`, `release`) to `done` via `yoke_core.domain.update_status`. This ensures all tasks reach `done` status when their parent epic is done.

## Pinned Item Stage Flow

There is no global backlog-item progression and no Issue/Epic item-type
branch. The row's `workflow_id` is a registry key; the immutable
`workflow_version_id` selects the only authoritative ordered stage graph.

For a live item:

1. Read the pin with `yoke workflows item get YOK-N`.
2. Read the exact definition with
   `yoke workflows version get WORKFLOW VERSION`.
3. Find the active half-open skill binding for the current stage.
4. Invoke `/yoke <skill_id>`.
5. Let the target-stage gate references and definition policies decide whether
   the transition can commit.

A binding ends at its `through_stage_id`; reaching that stage hands the item to
the next skill rather than granting the current command ownership of the
rest of the graph. Definitions may reuse familiar ids such as `idea`,
`planned`, `implemented`, `release`, and `done`, but documentation must not
copy those ids into a workflow-independent progression.

During a compatible `release_stage` delivery tail, the skill may encounter
`needs-capability` or `awaiting-approval` on the deployment run. The item
remains at the pinned delivery stage while halted; after resolution, the
registered delivery skill resumes the run.

## Dispatch Chain (DB table: `epic_dispatch_chains`)

One row per universal worktree lane. The chain references the lane record and
never duplicates its branch or filesystem path.

**Columns:**

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Auto-increment primary key |
| `epic_id` | INTEGER | Numeric parent item ID |
| `item_worktree_id` | INTEGER | Universal lane record in `item_worktrees` |
| `queue` | TEXT | JSON array of task numbers |
| `current_index` | INTEGER | Index into queue |
| `current_task` | TEXT | Currently active task number |
| `current_attempt` | INTEGER | Retry counter for current task |
| `max_attempts` | INTEGER | Retry limit (default 5) |
| `no_chain` | INTEGER | 1 = single-task dispatch, no auto-advance |
| `started_at` | TEXT | ISO timestamp |
| `last_updated` | TEXT | ISO timestamp |

**How auto-chaining works:**
1. The generated-task skill selected by the parent item's pinned binding
   queries for the existing chain record via the epic dispatch-chain reader
2. If current task is `implementing` → recovering from crash
3. If current task is already in terminal success (`implemented` or `done`) → advance `current_index`, start next
4. Before executing next, check dependencies. If unmet → set `blocked`, stop chain
5. Chain state survives crashes, compaction, tab closes

## Epic Dashboard

Queried live from the `epic_tasks` DB table by the board renderer and status-update path. Shows:
- Epic summary (total, implementing, done, failed, blocked, stopped)
- Tasks grouped by worktree with status, issue link, dispatch attempts
- Tasks sorted by `task_num` (plan order), not by issue number

## Cross-Item Board (`.yoke/BOARD.md`)

BOARD.md is 100% auto-generated by the Python board pipeline. Per-item context goes in backlog item structured fields (read via `items get YOK-N body`). The board section between `<!-- YOKE:BOARD:START -->` and `<!-- YOKE:BOARD:END -->` markers is regenerated on every backlog mutation and status change.

The board is a presentation projection, not lifecycle authority. It classifies
each item's pinned stage and orthogonal blocked/frozen/run state through
`yoke_contracts.board.status`; `yoke_core.domain.board.BOARD_COLUMNS` owns the
API column order. Unknown published stages remain visible as unknown instead
of being silently assigned a lifecycle meaning.

Each row shows public reference, title, workflow, priority, status, and
progress (generated-task counts when `epic_tasks` rows exist). Task detail is
queried live from the DB through Yoke core.

Rebuilt on every status change and backlog mutation via the Python backlog and board surfaces.

## GitHub Integration

### Generated epic tasks
- The parent backlog item and its generated tasks are represented as linked
  GitHub issues
- Each task → child Issue (labeled `type:task`, `status:{status}`, `worktree:{branch}`)
- Linked via `gh-sub-issue` (falls back to checkbox list)
- Status transitions → label swap + comment via `yoke_core.domain.update_status`
- Progress notes → issue comments via `yoke_core.api.service_client_items`

### Standalone backlog items
- the backlog sync helper creates a GitHub issue from a backlog item
- Labels include `workflow:<workflow_id>`, `status:<stage>`, and
  `priority:{high|medium|low}`; the workflow value comes from the item's
  pinned registry identity
- Issue number stored in `github_issue` field (e.g., `#8`)
- registered lifecycle skills post status-change comments to linked issues
  through the sync surface
- Idempotent: `sync-item` skips if `github_issue` is already set

## Stable Local IDs

Tasks keep their local plan-order numbers permanently (1, 2, 3, etc.). DB records, dispatch chains, and progress notes all use local task numbers. GitHub issue numbers are metadata stored in the `epic_tasks.github_issue` column — they are never used as filenames or primary keys.

The `dependencies` column in `epic_tasks` uses comma-separated local task numbers (e.g., `"001,002"`). The `auto_unblock` function in `yoke_core.domain.update_status` resolves dependencies by querying the `epic_tasks` table for the dependency's status.
