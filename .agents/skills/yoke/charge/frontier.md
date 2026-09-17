# /yoke charge steps 1–3 — schedule, frontier table, dry run

## 1. Compute the schedule

Stamp the session mode so the board's active-session row reflects the live phase (default `wait` misrepresents an active charge). Downstream skills overwrite this when they take over via the step-6 dispatch.

```bash
yoke sessions touch --mode charge
```

Run the registered wrapper to get the claim-aware schedule JSON:

```bash
yoke charge schedule {project_flag} {item_flag} --wip-cap {wip_cap}
```

Omit `--project`/`--item` when argless so the schedule stays on the
workspace-home project; pass them only as an operator bypass.

Parse the JSON output. The response has this shape:

```json
{
 "project": "yoke",
 "sml_state": {"coherent": true},
 "selected_step": {
 "item_id": "PREFIX-N",
 "next_step": "conduct",
 "claim_state": "unclaimed",
 "rank": 0,
 ...
 },
 "ranked_steps": [
 {
 "item_id": "PREFIX-N",
 "title": "Some item title",
 "status": "planned",
 "priority": "high",
 "workflow_id": "epic",
 "workflow_version_id": 2,
 "adapter": "conduct",
 "next_step": "conduct",
 "rank": 0,
 "claim_state": "unclaimed",
 "blocked_by": [],
 "blocked_reasons": [],
 "unblocks_count": 3,
 "created_at": "2026-03-01T..."
 }
 ],
 "blocked_steps": [
 {
 "item_id": "PREFIX-N",
 "claim_state": "...",
 "gate_evaluations": [{"gate_point": "activation", "rationale": "..."}],
 ...
 }
 ],
 "frozen_steps": [...],
 "wip_cap": 5,
 "wip_active": 2,
 "conduct_eligible": [...]
}
```

If the command exits non-zero, print the error and stop.

**FrontierComputed telemetry** is emitted by the core Python frontier path (`yoke_core.domain.frontier_compute`) — `yoke charge schedule` triggers `compute_frontier()` internally, so the event still fires and the charge skill does not emit it directly.

## 2. Present the frontier table

Filter the ranked steps to assignable claim states first. Iterate `ranked_steps[]` and keep only steps whose `claim_state` is `unclaimed`, `claimed_by_self`, or `claimed_by_stale` — exclude `claimed_by_other_live` (held by another live session). The kept list is the operator-facing Runnable table; the filtered count goes in a separate diagnostic line so the operator still sees that ranked-but-unassignable work exists.

Print a formatted summary to the operator. Use the following layout:

```
## Frontier — {project} (WIP: {wip_active}/{wip_cap})

## Runnable ({count_assignable})
| # | Item | Title | Status | Adapter | Priority | Unblocks |
|---|------|-------|--------|---------|----------|----------|
| 1 | PREFIX-N | Some title | planned | conduct | high | 3 |
| 2 | PREFIX-N | Another title | refined-idea | shepherd | medium | 0 |
...
```

If any ranked step was filtered because of `claim_state='claimed_by_other_live'`, also print a diagnostic line right under the Runnable table:

```
Held by other live sessions: {count_live_claimed} (visible on the ranked frontier but not assignable to this session)
```

If there are blocked items, also print (read from `blocked_steps[]`):

```
## Blocked ({count})
| Item | Title | Status | Blocked By | Gate | Rationale |
|------|-------|--------|------------|------|-----------|
| PREFIX-N | Blocked item | implementing | PREFIX-N | activation | Must complete PREFIX-N first |
...
```

For each blocked item, prefer `gate_evaluations` (always present on `yoke charge schedule` `blocked_steps[]`) over `blocked_reasons`. Surface `gate_point` and `rationale` from the unsatisfied gate evaluation.

If there are frozen items, print a count line (from `frozen_steps[]`):

```
## Frozen: {count} items (excluded from frontier)
```

If `selected_step` is empty and `runnable_elsewhere` is not, print the
elsewhere note and stop. If both are empty, print:

```
No runnable items on the frontier. Consider:
 /yoke feed — to materialize new work
 /yoke doctor — to check system health
```

If every ranked step was filtered specifically because they are all `claimed_by_other_live`, name the situation explicitly so the operator does not interpret an empty Runnable table as an empty frontier:

```
All ranked work is currently held by other live sessions. Nothing assignable to this session.
```

**Emit ChargeDecisionMade event** before stopping:

```sh
yoke events emit \
 --name "ChargeDecisionMade" \
 --kind lifecycle \
 --type charge \
 --source-type skill \
 --severity INFO \
 --outcome skipped \
 --context "{\"item_id\":\"\",\"adapter\":\"\",\"dispatched\":false,\"reason\":\"no_runnable_items\",\"project\":\"{project}\"}"
```

Then stop (nothing to dispatch).

## 3. Handle --dry-run

If `--dry-run` was passed, print:

```
(dry-run mode — no dispatch)
```

**Emit ChargeDecisionMade event** before stopping:

```sh
yoke events emit \
 --name "ChargeDecisionMade" \
 --kind lifecycle \
 --type charge \
 --source-type skill \
 --severity INFO \
 --outcome skipped \
 --context "{\"item_id\":\"\",\"adapter\":\"\",\"dispatched\":false,\"reason\":\"dry_run\",\"project\":\"{project}\"}"
```

Then stop. Do not confirm or dispatch.


Next: [`select-and-dispatch.md`](select-and-dispatch.md).
