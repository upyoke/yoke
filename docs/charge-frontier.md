# Charge Frontier

The charge frontier is the computation that determines which backlog items are eligible for work right now, ranks them by priority, and classifies each into a downstream delivery adapter. It powers the `/yoke charge` command and the `/yoke do` session orchestrator.

## Overview

The frontier partitions all charge-relevant items for a project into three buckets:

- **Runnable** -- items with no unsatisfied activation-gate hard-block dependencies, not frozen, ranked by priority.
- **Blocked** -- items with at least one unsatisfied activation-gate hard-block dependency. Each carries human-readable reasons.
- **Frozen** -- items with `frozen = 1`, excluded from the active frontier entirely.

A WIP cap limits how many conduct-eligible items are returned, preventing overcommitment.

## Algorithm

The `compute_frontier()` function exported by `packages/yoke-core/src/yoke_core/domain/frontier.py` and implemented in `packages/yoke-core/src/yoke_core/domain/frontier_compute.py` owns the full computation:

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

### Step 5: Classify adapter categories

Each item is classified into a downstream adapter based on its current status:

| Status | Adapter | Description |
|--------|---------|-------------|
| `idea` (epic) | `refine` | Epic needs refinement |
| `idea` (issue) | `refine` | Issue needs refinement |
| `refining-idea` (epic) | `refine` | Epic refinement in progress |
| `refining-idea` (issue) | `refine` | Issue refinement in progress |
| `refined-idea` (epic) | `shepherd` | Epic ready for shepherd pipeline |
| `refined-idea` (issue) | `conduct` | Issue ready for implementation |
| `planning` (epic) | `shepherd` | Epic planning in progress |
| `plan-drafted` (epic) | `refine` | Epic plan drafted, needs refinement |
| `refining-plan` (epic) | `refine` | Epic plan refinement in progress |
| `planned` (epic) | `conduct` | Epic ready for implementation work |
| `implementing` (epic) | `conduct` | Epic implementation in progress |
| `implementing` (issue) | `conduct` | Issue implementation in progress |
| `reviewing-implementation` (epic) | `conduct` | Epic implementation under review |
| `reviewing-implementation` (issue) | `conduct` | Issue implementation under review |
| `reviewed-implementation` (epic) | `polish` | Epic review complete, queued for finishing review |
| `reviewed-implementation` (issue) | `polish` | Issue review complete, queued for finishing review |
| `polishing-implementation` (epic) | `polish` | Epic finishing review in progress |
| `polishing-implementation` (issue) | `polish` | Issue finishing review in progress |
| `implemented` | `usher` | Ready for merge/deploy |
| `release` | `usher` | In deployment pipeline |
| `failed` | `wait` | Exceptional state, needs resolution |
| `done` | `skip` | Terminal, not actionable |
| `cancelled` | `skip` | Terminal, not actionable |
| `stopped` | `skip` | Terminal, not actionable |

The frontier adapter is the raw ranking category. The scheduler then remaps issue `conduct`-classified implementation states (`refined-idea`, `implementing`, `reviewing-implementation`) to `next_step=advance`, while epic implementation states remain `next_step=conduct`.

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
`runtime/harness/codex/manifest.json`).

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
 item_id: str # "YOK-N"
 title: str
 status: str # canonical status
 priority: str # high, medium, low
 project: str
 item_type: str # epic or issue
 adapter: AdapterCategory # refine, shepherd, conduct, polish, usher, wait, skip
 blocked_by: List[str] # ["YOK-N"] (blocked items only)
 blocked_reasons: List[str] # human-readable reasons
 unblocks_count: int # direct activation-gate dependents
 downstream_depth: int # longest downstream activation chain
 created_at: str # ISO 8601
```

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
 "item_id": "YOK-N",
 "title": "Implement widget",
 "status": "planned",
 "priority": "high",
 "project": "yoke",
 "item_type": "epic",
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

Outputs the same JSON structure as the REST endpoint. The service client resolves the canonical Yoke DB from main-repo and worktree contexts. This is the retained operator/debug adapter for the `GET /v1/charge/frontier` route; agents reading the frontier in-process call the typed dataclass return from `yoke_core.domain.frontier.compute_frontier` directly. Yoke control-plane mutations (claim acquire/release, item structured-field writes, lifecycle transitions, DB-claim amendments) route through the function-call surface — see [`docs/db-reference/functions.md`](db-reference/functions.md) and the operator-readable [`docs/atlas.md`](atlas.md). External tooling (git, pytest, package managers, `rg` / `grep`) stays command-shaped under the permanent-boundary classification.

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
3. **Select** -- use the highest-ranked item (or `--item YOK-N` override).
4. **Confirm** -- ask the operator to confirm the dispatch target.
5. **Dispatch** -- invoke the appropriate downstream skill based on the item's `next_step` (not the raw `adapter`):
 - `refine` routes to `/yoke refine YOK-N`
 - `shepherd` routes to `/yoke shepherd YOK-N`
 - `conduct` routes to `/yoke conduct YOK-N` (epics)
 - `advance` routes to `/yoke advance YOK-N implementation` (issues)
 - `polish` routes to `/yoke polish YOK-N`
 - `usher` routes to `/yoke usher YOK-N`
 - `wait` reports blockers and stops

### Arguments

| Flag | Default | Description |
|------|---------|-------------|
| `--dry-run` | off | Show frontier table and stop (no dispatch) |
| `--item YOK-N` | -- | Target a specific item instead of highest-ranked |
| `--project P` | `yoke` | Project scope |
| `--wip-cap N` | project-policy | WIP cap override; unset resolves the single-project DB `project-policy.wip_cap`, else `5` |

## Events

The charge flow emits structured events:

| Event | Kind | When | Emitter |
|-------|------|------|---------|
| `FrontierComputed` | workflow | On every `compute_frontier()` call | `packages/yoke-core/src/yoke_core/domain/frontier_compute.py` (core-owned) |
| `ChargeDecisionMade` | lifecycle | On every terminal charge exit | charge skill via `yoke_core.domain.events.emit_event` |

`FrontierComputed` is emitted by the core Python frontier path, not by the charge skill. See `packages/yoke-core/src/yoke_core/domain/frontier_compute.py` for the canonical emitter.

### ChargeDecisionMade envelope

```json
{
 "detail": {
 "item_id": "YOK-N",
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
- `requested_item_unavailable` — `--item YOK-N` targeted an item that was not runnable; `target_bucket` records whether it was `blocked`, `frozen`, or `not_found` in the frontier response
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
/yoke charge --item YOK-N
```

Skips ranking and targets YOK-N directly. If YOK-N is not in the runnable set, reports why (blocked, frozen, or terminal).

### Override WIP cap

```
/yoke charge --wip-cap 3
```

Restricts conduct-eligible items to 3 concurrent WIP slots.

## Related Documentation

- [commands.md](commands.md) -- full command reference
- [OVERVIEW.md](OVERVIEW.md) -- architecture overview with frontier-based flow
- [db-reference.md](db-reference.md) -- database schema (items, item_dependencies tables)
- [structured-logging-standard.md](structured-logging-standard.md) -- event envelope format
