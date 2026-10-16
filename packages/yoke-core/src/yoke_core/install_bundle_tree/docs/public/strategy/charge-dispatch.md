# Charge dispatch

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [Strategy](index.md) > Charge dispatch
<!-- /yoke:breadcrumbs -->

Read the frontier API and dispatch ranked work through its registered entrypoint.

## API Reference

### REST Endpoint

```
GET /v1/charge/frontier?project=yoke&wip_cap=30
```

**Parameters:**
- `project` (string, required) -- project to scope the frontier to. Missing context refuses as `project_required` and lists caller-accessible projects.
- `wip_cap` (integer, optional) -- maximum number of conduct-eligible items; omit to use the project's `project-policy.wip_cap` (source default `30`).

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
 "wip_cap": 30,
 "wip_active": 2,
 "conduct_eligible": [...]
}
```

### Registered frontier read

`frontier.list` serves the ranked frontier: `ready_rows`, `blocked_rows`,
and `dependency_edges`, every unsatisfied edge at the `activation`,
`integration` and `closure` gates whose dependent is not terminal, evaluated by
the shared dependency kernel. Each edge carries the blocker and dependent
refs, `gate_point`, `satisfaction`, `rationale`, the blocker's stage and title,
`blocking_terminal`, and `blocking_abandoned` (cancelled or stopped rather
than completed: only an abandoned blocker's edge can never clear). A blocker
that no longer resolves to an item still yields its edge, with empty blocker
details. For `fact:deployed:<env>` an `environment` with its
`delivery_state` (`live`, `deploying`, `not deployed`, `unregistered`) and
`in_delivery_flow` (whether any active flow of the blocker's project, or its
closing flow, reaches that environment). The Frontier page's Waiting graph
draws these edges; each gate is evaluated once per read. Adapter:

```text
yoke frontier list --project P --wip-cap 5 --json
```

Read `yoke frontier list --help` for available filters.

## Charge Dispatch Flow

The `/yoke charge` SKILL.md uses the frontier computation to drive the full charge loop:

1. **Compute** -- call `yoke charge schedule --json` to get the claim-aware ranked frontier.
2. **Present** -- display a formatted table of runnable items with adapter classifications.
3. **Select** -- use the highest-ranked item (or `--item PREFIX-N` override).
4. **Confirm** -- ask the operator to confirm the dispatch target.
5. **Dispatch** -- invoke the item's returned `entrypoint` from
   `charge.schedule`. The server renders it from the binding-derived `next_step`
   and the true public item ref using the launch mandate's own mapping. The
   raw `adapter` remains a ranking diagnostic. A `wait` step has no entrypoint
   and reports blockers. A missing entrypoint on a runnable step refuses as
   `entrypoint_unavailable`: inspect the item's pin with
   `yoke workflows item get PREFIX-N --json`, read its definition with
   `yoke workflows version get <workflow> <version> --json`, and refresh the
   schedule against a serving build that exposes the entrypoint.

### Arguments

| Flag | Default | Description |
|------|---------|-------------|
| `--dry-run` | off | Show frontier table and stop (no dispatch) |
| `--item PREFIX-N` | -- | Target a specific item instead of highest-ranked |
| `--project P` | workspace home | Explicit project scope; bypasses the workspace-home filter |
| `--wip-cap N` | project-policy | WIP cap override; unset resolves the single-project DB `project-policy.wip_cap`, else the `RECOGNIZED_PROJECT_KEYS` source default (`30`) |

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

### Charge the workspace-home project

```
/yoke charge
```

Computes the all-projects schedule, keeps the invoking checkout's
project, and dispatches that top item. When only other projects are
runnable, the schedule returns `runnable_elsewhere` instead of
assigning. `--project` or `--item` bypasses the filter.

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


## Related

- [Charge frontier](charge-frontier.md)
