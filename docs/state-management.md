# State Management

All authoritative Yoke state lives in the configured Postgres authority. Compacting, restarting, crashing, or switching tabs never loses state.

## Backlog Registry

Every trackable item gets a stable `YOK-N` ID that persists through its entire lifecycle. The registry is the single source of truth for all items — ideas, epics, and standalone issues.

### ID System

- **Format:** `YOK-N` (e.g.) — prefixed to avoid confusion with GitHub issue `#N`
- **Scope:** per-repo, monotonically increasing
- **Counter:** DB auto-increment on the `items` table.
- **Stability:** local ID never changes. GitHub issue number is a separate metadata field (`github_issue`).
- **Tasks within epics** keep plan-order numbering (001, 002) — internal to epic, not global YOK-N IDs.

### Item Types

| Type | Description | Lifecycle |
|------|-------------|-----------|
| `epic` | Big feature, needs spec + task decomposition | `idea → refining-idea → refined-idea → planning → plan-drafted → refining-plan → planned → implementing → reviewing-implementation → reviewed-implementation → polishing-implementation → implemented → release → done` |
| `issue` | Small, single unit of work | `idea → refining-idea → refined-idea → implementing → reviewing-implementation → reviewed-implementation → polishing-implementation → implemented → release → done` |

After merge and QA, items reach `implemented` and enter the **delivery lifecycle** owned by the Usher skill, which manages the `implemented → release → done` transition through deployment runs (see Delivery Lifecycle below). Two halt states (`needs-capability`, `awaiting-approval`) may interrupt the delivery flow. Items in `release` do NOT count toward the WIP cap. Type indicates scope (epic = has tasks, issue = single unit), not which statuses are available. Skipping states is allowed.

### Status Vocabulary

| Status | Owned by | Meaning |
|--------|----------|---------|
| `idea` | Human / Refine | Filed, not yet defined |
| `refining-idea` | Refine (`/yoke refine`) | PM is writing the spec |
| `refined-idea` | Refine (`/yoke refine`) | PM + Boss have specified it, ready to advance (issues) or shepherd (epics) |
| `planning` | Shepherd (epics only) | Architect is decomposing |
| `plan-drafted` | Shepherd (epics only) | Architect's initial plan + task decomposition captured, awaiting plan refinement |
| `refining-plan` | Refine (`/yoke refine`, epics only) | Plan under refinement after critique/simulation |
| `planned` | Refine (epics only) | Architecture decomposed and approved, ready to conduct |
| `implementing` | Advance (issues) / Conduct (epics) | Engineer dispatched |
| `reviewing-implementation` | Advance (issues) / Conduct (epics) | Engineer done, under review in the same worktree |
| `reviewed-implementation` | Advance (issues) / Conduct (epics) | Review complete, ready for polish |
| `polishing-implementation` | Polish (`/yoke polish`) | Final polish in progress |
| `implemented` | Polish (`/yoke polish`) | Polish complete, awaiting deployment handoff |
| `release` | Usher | Enrolled in an executing deployment run |
| `done` | Usher | Deployment run succeeded and all blocking QA satisfied (or no deployment flow) |
| `cancelled` | Human | Explicitly cancelled |

> **Ownership note:** `/yoke refine` owns idea refinement for both issues and epics, and plan refinement for epics. `/yoke shepherd` is an epic-only bridge that owns `refined-idea -> planning -> plan-drafted`. See [lifecycle.md](lifecycle.md) for the full command-boundary guide.

**Note:** `needs-capability` and `awaiting-approval` are **halt states** on the deployment run, not item statuses. Items at these halt states remain at `status=release`. The `current_stage` field on the `deployment_runs` row tracks position within the deployment pipeline. See Delivery Lifecycle below for details.

### Item Fields

Items are read via `yoke items get YOK-N <field>`. The `body` field is a virtual rendered field assembled on demand from structured fields — it is not stored in the DB.

**Fields:**
- `id` — stable `YOK-N` identifier, never changes
- `title` — human-readable title
- `type` — `epic` or `issue`
- `status` — lifecycle state (see Item Types above)
- `priority` — `high`, `medium`, or `low`
- `epic` — slug of linked epic directory (null if not yet planned)
- `github_issue` — GitHub issue reference, populated on sync (null if unsynced)
- `created` — ISO timestamp, set on creation
- `updated` — ISO timestamp, updated on every field change
- `merged_at` — ISO timestamp, automatically populated by `yoke_core.engines.done_transition` when the item transitions to `done` (set to current UTC timestamp if null). Not overwritten if already set (e.g., by the merge pipeline). Tracks when the item's code was finalized on main.

**Item-level dependencies** are stored in the `item_dependencies` table (not as an item field). Every row is a canonical blocker with `gate_point` (`activation`, `integration`, or `closure`) and `satisfaction` (`status:done`, `status:implemented`, or `fact:merged`). Each row carries a `rationale` (human-readable) and `evidence_json` (structured provenance). A shared dependency-planning kernel (`dependency_planning.py`) evaluates gates and plans candidate sets for all consumers. Transition and dispatch gates call the hard-block gate or the dependency-planning service commands. See `.yoke/docs/db-reference.md` for the full schema.

### Counter Mechanics

When the backlog create path inserts an item:
1. Insert into DB (auto-increment assigns next ID, e.g., `19`)
2. Item is accessible via `items get YOK-N body`
3. Trigger board rebuild

The counter never decrements. Deleted items leave gaps (IDs are never reused).

## Backlog Item Lifecycle

When a backlog item flows through the Yoke pipeline, these status transitions happen automatically:

| Event | Command | Backlog Status | Backlog Fields Updated |
|-------|---------|----------------|----------------------|
| Spec refinement started | `/yoke refine` | → `refining-idea` | structured spec field populated |
| Spec approved | `/yoke refine` | → `refined-idea` | — |
| Planning started (epics) | `/yoke shepherd` | → `planning` | — |
| Plan drafted (epics) | `/yoke shepherd` | → `plan-drafted` | epic task decomposition captured |
| Plan refinement (epics) | `/yoke refine` | → `refining-plan` → `planned` | `technical_plan` / `worktree_plan` updated |
| Implementation started | `/yoke advance YOK-N implementation` (issues) / `/yoke conduct YOK-N` (epics) | → `implementing` | worktree created |
| Implementation review | Review loop in same worktree | → `reviewing-implementation` | — |
| Implementation review complete | Review passes | → `reviewed-implementation` | — |
| Polish complete | `/yoke polish` | → `polishing-implementation` → `implemented` | — |
| Merged to main | `/yoke usher YOK-N` (handles merge + deploy) | `merged_at` set | — |
| Usher creates run | `/yoke usher YOK-N` (accepts `implemented` status) | — | Deployment run created |
| Run starts executing | Usher starts deployment pipeline | → `release` | Run status set to `executing` |
| Capability missing | Usher executor exits code 2 | remains `release` | Run halted at `needs-capability` |
| Approval needed | Usher hits approval gate | remains `release` | Run halted at `awaiting-approval` |
| Approval granted | `/yoke approve YOK-N` | remains `release` | Run's `current_stage` advanced |
| Deployment complete | Usher completes all stages + blocking QA satisfied | → `done` | Run status set to `succeeded` |

**Deployment flow architecture:** Post-merge deployment is managed by the Usher skill via deployment runs (`deployment_runs` table). Each run references a `deployment_flow`. Item-bound runs operate on one or more items through `deployment_run_items`; environment-level Yoke deploys may intentionally operate on zero items. Stage authority lives on the run (`current_stage`), not on individual items. See `.yoke/docs/db-reference.md` for the `deployment_runs`, `deployment_run_items`, `deployment_run_qa`, `deployment_flows`, `sites`, `environments`, and `project_capabilities` table schemas.

Specs, plans, and review artifacts live in structured item fields (`spec`, `technical_plan`, `worktree_plan`, `shepherd_log`, `test_results`, etc.). `items.body` is a virtual rendered field assembled on demand from these structured fields — not stored in the DB, not a write target.

## Delivery Lifecycle

After an item completes implementation and reaches `implemented`, ownership transfers from Conduct/Polish to the **Usher** skill. The Usher manages the `implemented → release → done` transition by creating and executing deployment runs.

### Usher Ownership Boundary

The Usher owns the delivery lifecycle exclusively. It does not touch anything pre-merge. The boundary is:

- **Advance / Conduct** owns: `implementing → reviewing-implementation → reviewed-implementation` (implementation and review loop in the existing worktree lane set)
- **Polish** owns: `reviewed-implementation → polishing-implementation → implemented` (finishing review, cleanup, verification, and local polish commits across the changed lanes)
- **Usher** owns: `implemented → release → done` (creates deployment runs, executes stages; halt states `needs-capability` / `awaiting-approval` may interrupt the flow while item remains at `status=release`)

The handoff occurs when an item reaches `implemented` status. By default, `implemented` is a manual planning boundary — the operator decides when and how to usher items:

- **Default:** The advance finalize phase stops at `implemented` with next-step guidance: run `/yoke usher YOK-N` to merge and deploy. The operator controls merge ordering, batching (ushering multiple items together), and deployment timing.
- **Fresh command entrypoint required:** Even when the operator already knows usher should run next, `/yoke usher` starts as its own command entrypoint and claims the item itself. Advance/polish must stop at their handoff boundary instead of carrying claim ownership across commands.
- **Conduct-managed items:** The conduct pipeline outputs the same next-step instructions.

**lifecycle fix:** Done transitions are handled exclusively by `/yoke usher YOK-N`, which manages the full pipeline: merge → deploy → verify → done-transition. `/yoke advance YOK-N done` redirects to usher.

### Delivery Pipeline Internals

Run mechanics, halt states, executor types, and ephemeral environments live in [state-management/delivery-internals.md](state-management/delivery-internals.md):

- **Deployment runs** — stage authority on the run row, item lifecycle during a run, `deploy_stage` cache.
- **Halt states** — `needs-capability`, `awaiting-approval`, GitHub-protection-rule integration.
- **Capability self-invention** — exit-code-2 protocol, template registration, operator resume.
- **Human approval gate** — `/yoke approve` flow.
- **Executor dispatch** — `auto`, `script`, `health-check`, `human-approval`, `github-actions-workflow`.
- **Usher state machine** — full state diagram.
- **No-flow fast path** — `implemented → done` direct transition.
- **Ephemeral environments** — conduct-phase preview environments tracked in `ephemeral_environments`.

## Epic Task State (DB table: `epic_tasks`)

One row per task. Created by `yoke_core.api.service_client_items`. Updated by `yoke_core.domain.update_status`.

**Columns:**

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Auto-increment primary key |
| `epic_id` | TEXT | Parent epic slug (e.g., "auth-api") |
| `task_num` | INTEGER | Plan-order number (e.g., 1, 2, 3) |
| `title` | TEXT | Task title |
| `worktree` | TEXT | Branch/worktree name |
| `context_estimate` | TEXT | Size estimate (e.g., "S", "30k") |
| `dependencies` | TEXT | Comma-separated task numbers |
| `status` | TEXT | Current lifecycle status |
| `dispatch_attempts` | INTEGER | Auto-incremented on each `implementing` transition |
| `github_issue` | TEXT | GitHub issue reference (e.g., "#42") |

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

## Backlog Item Status Flow

**Issue items:**
```
idea → refining-idea → refined-idea → implementing → reviewing-implementation → reviewed-implementation → polishing-implementation → implemented → release → done
```

**Epic items:**
```
idea → refining-idea → refined-idea → planning → plan-drafted → refining-plan → planned → implementing → reviewing-implementation → reviewed-implementation → polishing-implementation → implemented → release → done
```

- `idea` → `refining-idea`: `/yoke refine` starts spec refinement
- `refining-idea` → `refined-idea`: `/yoke refine` completes spec refinement
- `refined-idea` → `planning`: `/yoke shepherd` starts epic planning
- `planning` → `plan-drafted`: `/yoke shepherd` captures the initial task/worktree plan
- `plan-drafted` → `refining-plan`: `/yoke refine` starts plan refinement
- `refining-plan` → `planned`: `/yoke refine` completes plan refinement
- `refined-idea` → `implementing`: `/yoke advance YOK-N implementation` creates or re-enters the issue worktree
- `planned` → `implementing`: `/yoke conduct YOK-N` starts epic implementation from the approved plan
- `implementing` → `reviewing-implementation`: engineering work is submitted for review
- `reviewing-implementation` → `reviewed-implementation`: Review complete
- `reviewed-implementation` → `polishing-implementation`: `/yoke polish` started
- `polishing-implementation` → `implemented`: `/yoke polish` complete
- `implemented` → `release`: Deployment run starts executing
- `implemented` → `done`: No-flow items go directly to done
- `release` → `done`: Run succeeded + all blocking QA satisfied
- `cancelled`: any status → `cancelled` (human override)

**Delivery halt states:** During the `release → done` transition, the Usher may encounter `needs-capability` or `awaiting-approval` conditions on the deployment run. The item's `status` remains `release` while halted. After the operator resolves the halt, the Usher resumes the deployment run.

## Dispatch Chain (DB table: `epic_dispatch_chains`)

One row per worktree. Created by `yoke_core.api.service_client_items`. Updated by `yoke_core.domain.update_status` on status changes.

**Columns:**

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Auto-increment primary key |
| `epic_id` | TEXT | Parent epic slug |
| `worktree` | TEXT | Branch/worktree name |
| `worktree_path` | TEXT | Absolute filesystem path |
| `queue` | TEXT | JSON array of task numbers |
| `current_index` | INTEGER | Index into queue |
| `current_task` | TEXT | Currently active task number |
| `current_attempt` | INTEGER | Retry counter for current task |
| `max_attempts` | INTEGER | Retry limit (default 5) |
| `no_chain` | INTEGER | 1 = single-task dispatch, no auto-advance |
| `started_at` | TEXT | ISO timestamp |
| `last_updated` | TEXT | ISO timestamp |

**How auto-chaining works:**
1. The orchestrator (conduct or dispatch) queries for existing chain record via the epic dispatch-chain reader
2. If current task is `implementing` → recovering from crash
3. If current task is already in terminal success (`implemented` or `done`) → advance `current_index`, start next
4. Before executing next, check dependencies. If unmet → set `blocked`, stop chain
5. Chain state survives crashes, compaction, tab closes

## Epic Dashboard

Queried live from the `epic_tasks` DB table by the board renderer and status-update path. Shows:
- Epic summary (total, implementing, done, failed, blocked, stopped)
- Tasks grouped by worktree with status, issue link, dispatch attempts
- Tasks sorted by `task_num` (plan order), not by issue number

## Cross-Epic Board (`.yoke/BOARD.md`)

BOARD.md is 100% auto-generated by the Python board pipeline. Per-item context goes in backlog item structured fields (read via `items get YOK-N body`). The board section between `<!-- YOKE:BOARD:START -->` and `<!-- YOKE:BOARD:END -->` markers is regenerated on every backlog mutation and status change.

Flat kanban: one item, one row, one place. Shows all backlog items grouped by status:
- **Active** — `implementing`, `reviewing-implementation`, `reviewed-implementation`, `polishing-implementation`, `implemented`, `release` (work in progress)
- **Pipeline** — `refining-idea`, `refined-idea`, `planning`, `plan-drafted`, `refining-plan`, `planned` (moving through the spec pipeline)
- **Backlog** — `idea` (raw captures, not yet spec'd)
- **Done** — `done` (finished)

Each row shows ID, title, type, priority, status, and progress (task counts for epics from the `epic_tasks` DB table). Per-epic task detail is queried live from the DB through Yoke core.

Rebuilt on every status change and backlog mutation via the Python backlog and board surfaces.

## GitHub Integration

### Epic tasks
- Each epic → parent Issue (labeled `type:epic`)
- Each task → child Issue (labeled `type:task`, `status:{status}`, `worktree:{branch}`)
- Linked via `gh-sub-issue` (falls back to checkbox list)
- Status transitions → label swap + comment via `yoke_core.domain.update_status`
- Progress notes → issue comments via `yoke_core.api.service_client_items`

### Standalone backlog items
- the backlog sync helper creates a GitHub issue from a backlog item
- Labels: `type:{epic|issue}`, `priority:{high|medium|low}`
- Issue number stored in `github_issue` field (e.g., `#8`)
- `/yoke advance` posts status-change comments to linked issues via `post-comment`
- Idempotent: `sync-item` skips if `github_issue` is already set

## Stable Local IDs

Tasks keep their local plan-order numbers permanently (1, 2, 3, etc.). DB records, dispatch chains, and progress notes all use local task numbers. GitHub issue numbers are metadata stored in the `epic_tasks.github_issue` column — they are never used as filenames or primary keys.

The `dependencies` column in `epic_tasks` uses comma-separated local task numbers (e.g., `"001,002"`). The `auto_unblock` function in `yoke_core.domain.update_status` resolves dependencies by querying the `epic_tasks` table for the dependency's status.
