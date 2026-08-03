# Charge Frontier

The charge frontier is the computation that determines which backlog items are eligible for work right now, ranks them by priority, and classifies each into a downstream delivery adapter. It powers the `/yoke charge` command and the `/yoke do` session orchestrator.

## Overview

The frontier partitions all charge-relevant items for a project into three buckets:

- **Runnable** -- items with no unsatisfied activation-gate hard-block dependencies, not frozen, ranked by priority.
- **Blocked** -- items with at least one unsatisfied activation-gate hard-block dependency. Each carries human-readable reasons.
- **Frozen** -- items with `frozen = 1`, excluded from the active frontier entirely.

A WIP cap limits how many conduct-eligible items are returned, preventing overcommitment.

## Algorithm

The `compute_frontier()` function exported by `yoke_core.domain.frontier` and implemented in `yoke_core.domain.frontier_compute` owns the full computation:

### Step 1: Fetch candidate items

Query the charge-relevant status subset for the target project. The candidate set includes refine, shepherd, conduct, polish, and usher handoff states plus items where `items.blocked = 1`. Only `done`, `cancelled`, `stopped`, and `failed` are excluded from the frontier.

### Step 2: Resolve hard-block dependencies

Query the `item_dependencies` table for all canonical blocker dependencies at `gate_point='activation'`. Evaluate each dependency using its `satisfaction` condition (`status:done`, `status:implemented`, or `fact:merged`) and build a map from each dependent item to its list of unsatisfied blockers.

### Step 3: Compute direct activation unblocking value

For each item, count how many other items it blocks at the `activation` gate.
This remains a useful tiebreaker within the same downstream depth, but
integration and closure edges do not influence frontier start-order ranking.

### Step 3b: Compute downstream activation depth

Traverse the activation-gate dependency graph and compute each item's maximum
downstream depth (longest blocker-to-dependent chain). This captures
critical-path leverage: the head of a deep enabling chain should rank above a
broader but shallower fan-out when priority is equal.

### Step 4: Count current WIP

Count items in `implementing` or `reviewing-implementation` status for the project (excluding frozen items). These are the statuses that consume implementation WIP. `reviewed-implementation` and `polishing-implementation` are finishing-review states and do not consume conduct WIP slots.

### Step 5: Resolve the registered skill

Each item loads its immutable `workflow_id` / `workflow_version_id` pin. The
runtime finds the current stage in that definition and resolves the registered
skill binding for the stage. The frontier adapter remains a coarse ranking
category; scheduler `next_step` is the skill binding and is the dispatch
truth.

Items with unsatisfied activation-gate hard-block dependencies are reclassified to `wait` regardless of their status-based adapter. Items with `items.blocked = 1` are also reported in the blocked bucket even when they do not have a hard-block dependency row.

### Step 6: Partition and rank

- **Frozen items** go to the frozen bucket (separate reporting).
- **Blocked items** (activation-gate hard-block dependencies unsatisfied or `items.blocked = 1`) go to the blocked bucket with their blocker list and human-readable reasons.
- **Runnable items** are sorted by the deterministic ranking algorithm (see below).

### Step 7: Enforce WIP cap

The WIP cap limits remaining implementation capacity. In practice, scheduler suppression applies to epic `conduct` work; issue `advance` re-entry remains schedulable, but items already in `implementing` or `reviewing-implementation` still contribute to `wip_active`.

At offer time, the scheduler's lane/path filter uses the session's resolved
executor identity rather than a hand-passed free-form lane guess. Surface-
specific executors first resolve their default lane through the project's
DB-backed `session-routing` capability (exact
`executor_default_lane_<token>` -> wildcard
`executor_default_lane_<prefix>*` (longest prefix wins) ->
`executor_default_lane_unknown` -> `primary`). Machine config is only the
no-project/operator fallback. Downstream-path truth comes from the shared
registry plus coarse-manifest limitations (`codex-desktop` ->
the installed Codex manifest).

## Ranking Algorithm

Runnable items are sorted by five criteria in descending priority:

1. **Priority** -- `high` > `medium` > `low`.
2. **Downstream depth** -- items at the head of longer activation-gate chains rank higher.
3. **Direct activation unblocking value** -- within the same depth, items that directly unblock more activation-gate dependents rank higher.
4. **Lifecycle stage** -- items closer to `done` rank higher (prefer finishing over starting).
5. **Item age** -- older items rank higher (FIFO tiebreaker via ISO 8601 `created_at`).

The sort is stable and deterministic: identical DB state always produces identical ordering.

## Data Models

### FrontierItem

```python
@dataclass
class FrontierItem:
 item_id: int # internal items.id (scheduler-internal currency)
 title: str
 status: str # canonical status
 priority: str # high, medium, low
 project: str
 workflow_id: str
 workflow_version_id: int
 adapter: AdapterCategory # refine, shepherd, conduct, advance, dash, blitz, polish, usher, wait, skip
 blocked_by: List[str] # public text refs stored on item_dependencies rows
 blocked_reasons: List[str] # human-readable reasons
 unblocks_count: int # direct activation-gate dependents
 downstream_depth: int # longest downstream activation chain
 created_at: str # ISO 8601
```

The in-process dataclass carries the internal ``items.id``. Every serialized
surface (REST endpoints, service-client JSON, offer/NextAction payloads)
renders ``item_id`` as the item's TRUE public ref
(``{projects.public_item_prefix}-{items.project_sequence}`` — the prefix is
per-project, so the same shape renders ``EXT-12`` in one project and
``PLAT-12`` in another) via ``project_identity.render_item_ref`` — the
sequence and prefix may diverge from the internal id.

### FrontierResult

```python
@dataclass
class FrontierResult:
 runnable: List[FrontierItem] # ranked by priority
 blocked: List[FrontierItem] # have unsatisfied hard-blocks
 frozen: List[FrontierItem] # excluded (frozen=1)
 wip_cap: int # configured WIP limit
 wip_active: int # current WIP count
 conduct_eligible: List[FrontierItem] # runnable conduct items within WIP cap
```

### AdapterCategory

```python
class AdapterCategory(str, Enum):
 REFINE = "refine" # item needs refinement (idea, refining-idea, plan-drafted, refining-plan)
 SHEPHERD = "shepherd" # item needs maturation (refined-idea epic, planning epic)
 CONDUCT = "conduct" # item ready for implementation
 POLISH = "polish" # item reviewed, needs finishing review (reviewed-implementation, polishing-implementation)
 USHER = "usher" # item ready for deployment
 WAIT = "wait" # item blocked or exceptional
 SKIP = "skip" # item terminal, not actionable
```

## API Reference

### REST Endpoint

```
GET /v1/charge/frontier?project=yoke&wip_cap=5
```

**Parameters:**
- `project` (string, default: `"yoke"`) -- project to scope the frontier to.
- `wip_cap` (integer, default: `5`) -- maximum number of conduct-eligible items.

**Response:** JSON object matching the `FrontierResult` structure.

```json
{
 "runnable": [
 {
 "item_id": "PREFIX-N",
 "title": "Implement widget",
 "status": "planned",
 "priority": "high",
 "project": "yoke",
 "workflow_id": "epic",
 "workflow_version_id": 1,
 "adapter": "conduct",
 "blocked_by": [],
 "blocked_reasons": [],
 "unblocks_count": 3,
 "downstream_depth": 2,
 "created_at": "2026-03-01T12:00:00"
 }
 ],
 "blocked": [],
 "frozen": [],
 "wip_cap": 5,
 "wip_active": 2,
 "conduct_eligible": [...]
}
```

### Service Client CLI (operator/debug adapter)

```bash
python3 -m yoke_core.api.service_client charge-frontier \
 --project yoke \
 --wip-cap 5
```

Outputs the same JSON structure as the REST endpoint. The service client resolves the canonical Yoke DB from main-repo and worktree contexts. This is the retained operator/debug adapter for the `GET /v1/charge/frontier` route; agents reading the frontier in-process call the typed dataclass return from `yoke_core.domain.frontier.compute_frontier` directly. Yoke control-plane mutations (claim acquire/release, item structured-field writes, lifecycle transitions, DB-claim amendments) route through the function-call surface — see [`.yoke/docs/db-reference/functions.md`](db-reference/functions.md) and the operator-readable Atlas — the yoke source-repo doc `docs/atlas.md`. External tooling (git, pytest, package managers, `rg` / `grep`) stays command-shaped under the permanent-boundary classification.

### Domain Function

```python
from yoke_core.domain.frontier import compute_frontier

result = compute_frontier(conn, project="yoke", wip_cap=5)
# result is a FrontierResult dataclass
```

## Charge Dispatch Flow

The `/yoke charge` SKILL.md uses the frontier computation to drive the full charge loop:

1. **Compute** -- call `python3 -m yoke_core.api.service_client charge-frontier` to get the ranked frontier.
2. **Present** -- display a formatted table of runnable items with adapter classifications.
3. **Select** -- use the highest-ranked item (or `--item PREFIX-N` override).
4. **Confirm** -- ask the operator to confirm the dispatch target.
5. **Dispatch** -- invoke the registered skill in the item's `next_step`
   (not the raw `adapter`):
 - `refine` routes to `/yoke refine PREFIX-N`
 - `shepherd` routes to `/yoke shepherd PREFIX-N`
 - `conduct` routes to `/yoke conduct PREFIX-N`
 - `advance` routes to `/yoke advance PREFIX-N implementation`
 - `polish` routes to `/yoke polish PREFIX-N`
 - `usher` routes to `/yoke usher PREFIX-N`
 - `wait` reports blockers and stops

### Arguments

| Flag | Default | Description |
|------|---------|-------------|
| `--dry-run` | off | Show frontier table and stop (no dispatch) |
| `--item PREFIX-N` | -- | Target a specific item instead of highest-ranked |
| `--project P` | `yoke` | Project scope |
| `--wip-cap N` | project-policy | WIP cap override; unset resolves the single-project DB `project-policy.wip_cap`, else `5` |

## Events

The charge flow emits structured events:

| Event | Kind | When | Emitter |
|-------|------|------|---------|
| `FrontierComputed` | workflow | On every `compute_frontier()` call | `yoke_core.domain.frontier_compute` (core-owned) |
| `ChargeDecisionMade` | lifecycle | On every terminal charge exit | charge skill via `yoke_core.domain.events.emit_event` |

`FrontierComputed` is emitted by the core Python frontier path, not by the charge skill. See `yoke_core.domain.frontier_compute` for the canonical emitter.

### ChargeDecisionMade envelope

```json
{
 "detail": {
 "item_id": "PREFIX-N",
 "adapter": "conduct",
 "dispatched": true,
 "reason": "dispatched",
 "project": "yoke"
 }
}
```

The `reason` field distinguishes terminal outcomes:
- `dispatched` — item was dispatched to a downstream adapter
- `no_runnable_items` — frontier had no runnable items
- `dry_run` — `--dry-run` flag prevented dispatch
- `requested_item_unavailable` — `--item PREFIX-N` targeted an item that was not runnable; `target_bucket` records whether it was `blocked`, `frozen`, or `not_found` in the frontier response
- `operator_cancelled` — operator chose to cancel at confirmation
- `wait_adapter_encountered` — an unexpected `wait` adapter appeared at dispatch time and the command stopped without routing work

## Examples

### Check what is runnable without dispatching

```
/yoke charge --dry-run
```

Shows the frontier table and stops. Useful for situational awareness.

### Charge the default project

```
/yoke charge
```

Computes the frontier for the default project, presents the top item, and dispatches after confirmation.

### Charge a specific item

```
/yoke charge --item PREFIX-N
```

Skips ranking and targets PREFIX-N directly. If PREFIX-N is not in the runnable set, reports why (blocked, frozen, or terminal).

### Override WIP cap

```
/yoke charge --wip-cap 3
```

Restricts conduct-eligible items to 3 concurrent WIP slots.

## Related Documentation

- [commands.md](commands.md) -- full command reference
- `docs/OVERVIEW.md` (yoke source repo) -- architecture overview with frontier-based flow
- [db-reference.md](db-reference.md) -- database schema (items, item_dependencies tables)
- [structured-logging-standard.md](structured-logging-standard.md) -- event envelope format
