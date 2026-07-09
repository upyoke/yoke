---
name: charge
description: "Direct-mode entrypoint — compute the frontier, present the ranked table, confirm with operator, and dispatch to the correct downstream adapter."
argument-hint: "[--dry-run] [--item YOK-N] [--project P] [--wip-cap N]"
---

# /yoke charge

Direct-mode entrypoint for the charge flow. Computes the claim-aware schedule via `yoke charge schedule`, presents a formatted table of ranked items with their adapter classifications, confirms the top pick with the operator, and dispatches to the correct downstream skill (refine, shepherd, conduct, advance, polish, or usher). The `next_step` field is the dispatch truth: it applies type-aware epic/issue routing overrides that the raw `adapter` category does not. The `adapter` column remains in the table display for ranking diagnostics.

`yoke charge schedule` is claim-aware: each ranked step carries a `claim_state` (`unclaimed`, `claimed_by_self`, `claimed_by_other_live`, `claimed_by_stale`). Steps with `claim_state='claimed_by_other_live'` stay on the ranked frontier for diagnostics but must NOT appear in the operator-facing Runnable table or be selected for dispatch — that is the assignability rule defined in `runtime/api/domain/scheduler_types.py:is_assignable_claim_state`.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug not worth a ticket, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Arguments

- `--dry-run` — Show the frontier table and stop. Do not confirm or dispatch.
- `--item YOK-N` — Target a specific item instead of the highest-ranked one.
- `--project P` — Project scope (default: `yoke`).
- `--wip-cap N` — WIP cap override (default: 5).

## Philosophy

**Be the giant.** We stand on inherited shoulders; leave a leg up for the next agent by making this artifact cold-start complete. Charge is a routing handoff: present the frontier and dispatch rationale clearly enough that the chosen downstream skill can begin without re-litigating why it was selected.

**Think, don't just rank.** The frontier table is a decision aid, not a substitute for judgment. Surface blockers, adapter fit, and hidden readiness gaps instead of blindly following the top score.

## Steps

### 1. Compute the schedule

Stamp the session mode so the board's active-session row reflects the live phase (default `wait` misrepresents an active charge). Downstream skills overwrite this when they take over via the step-6 dispatch.

```bash
yoke sessions touch --mode charge
```

Run the registered wrapper to get the claim-aware schedule JSON:

```bash
_workspace=$(git rev-parse --show-toplevel)
yoke charge schedule \
 --project "{project}" \
 --wip-cap {wip_cap}
```

Where `{project}` and `{wip_cap}` come from the parsed arguments (or their defaults).

Parse the JSON output. The response has this shape:

```json
{
 "project": "yoke",
 "sml_state": {"coherent": true},
 "selected_step": {
 "item_id": "YOK-N",
 "next_step": "conduct",
 "claim_state": "unclaimed",
 "rank": 0,
 ...
 },
 "ranked_steps": [
 {
 "item_id": "YOK-N",
 "title": "Some item title",
 "status": "planned",
 "priority": "high",
 "item_type": "epic",
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
 "item_id": "YOK-N",
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

**FrontierComputed telemetry** is emitted by the core Python frontier path (`runtime/api/domain/frontier_compute.py`) — `yoke charge schedule` triggers `compute_frontier()` internally, so the event still fires and the charge skill does not emit it directly.

### 2. Present the frontier table

Filter the ranked steps to assignable claim states first. Iterate `ranked_steps[]` and keep only steps whose `claim_state` is `unclaimed`, `claimed_by_self`, or `claimed_by_stale` — exclude `claimed_by_other_live` (held by another live session). The kept list is the operator-facing Runnable table; the filtered count goes in a separate diagnostic line so the operator still sees that ranked-but-unassignable work exists.

Print a formatted summary to the operator. Use the following layout:

```
## Frontier — {project} (WIP: {wip_active}/{wip_cap})

### Runnable ({count_assignable})
| # | Item | Title | Status | Adapter | Priority | Unblocks |
|---|------|-------|--------|---------|----------|----------|
| 1 | YOK-N | Some title | planned | conduct | high | 3 |
| 2 | YOK-N | Another title | refined-idea | shepherd | medium | 0 |
...
```

If any ranked step was filtered because of `claim_state='claimed_by_other_live'`, also print a diagnostic line right under the Runnable table:

```
Held by other live sessions: {count_live_claimed} (visible on the ranked frontier but not assignable to this session)
```

If there are blocked items, also print (read from `blocked_steps[]`):

```
### Blocked ({count})
| Item | Title | Status | Blocked By | Gate | Rationale |
|------|-------|--------|------------|------|-----------|
| YOK-N | Blocked item | implementing | YOK-N | activation | Must complete YOK-N first |
...
```

For each blocked item, prefer `gate_evaluations` (always present on `yoke charge schedule` `blocked_steps[]`) over `blocked_reasons`. Surface `gate_point` and `rationale` from the unsatisfied gate evaluation.

If there are frozen items, print a count line (from `frozen_steps[]`):

```
### Frozen: {count} items (excluded from frontier)
```

If there are no assignable runnable items (after filtering), print:

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

### 3. Handle --dry-run

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

### 4. Select the target item

If `--item YOK-N` was passed:
- Find that item in the assignable Runnable table.
- If the item is on `ranked_steps[]` but with `claim_state='claimed_by_other_live'`, treat it as unavailable and report `claimed_by_other_live` (held by another live session) as the reason.
- If not found, also check `blocked_steps[]` and `frozen_steps[]` and report why it cannot be dispatched.
- **Emit ChargeDecisionMade event** before stopping:

```sh
yoke events emit \
 --name "ChargeDecisionMade" \
 --kind lifecycle \
 --type charge \
 --source-type skill \
 --severity INFO \
 --outcome skipped \
 --item-id "{requested_item_id}" \
 --context "{\"adapter\":\"\",\"dispatched\":false,\"reason\":\"requested_item_unavailable\",\"target_bucket\":\"{target_bucket}\",\"project\":\"{project}\"}"
```

Where `{target_bucket}` is `blocked`, `frozen`, or `not_found` based on where the item was found in the frontier response (or not found at all). Then stop.
- Use that item as the target.

If no `--item` flag:
- Use the first (highest-ranked) item from the assignable Runnable table as the target. This matches `selected_step` from the schedule response when present; if `selected_step` is `null` and the assignable Runnable table is empty, stop with the no-runnable-items wording from step 2.

### 5. Confirm with operator

Present the selected item and its dispatch target:

```
Selected: {item_id} — {title}
 Status: {status}
 Adapter: {adapter}
 Next step: {next_step}
 Action: Will invoke /yoke {next_step} {item_id}
```

Ask the operator to confirm. Use the following options:
- "Yes, dispatch to /yoke {next_step} {item_id}"
- "Pick a different item (specify YOK-N)"
- "Cancel — do not dispatch"

If the operator picks a different item, find it in the assignable Runnable table and repeat step 5 with the new item.

If the operator cancels, **emit ChargeDecisionMade event** before stopping:

```sh
yoke events emit \
 --name "ChargeDecisionMade" \
 --kind lifecycle \
 --type charge \
 --source-type skill \
 --severity INFO \
 --outcome skipped \
 --item-id "{item_id}" \
 --context "{\"next_step\":\"{next_step}\",\"adapter\":\"{adapter}\",\"dispatched\":false,\"reason\":\"operator_cancelled\",\"project\":\"{project}\"}"
```

Where `{item_id}`, `{next_step}`, and `{adapter}` are from the selected item (if one was selected before cancellation; empty otherwise). Then stop.

### 6. Dispatch to downstream skill

Based on the confirmed item's `next_step` field, dispatch as follows. The `next_step` value is the dispatch truth — it applies type-aware epic/issue routing overrides (e.g., issue implementation routes to `advance`, not `conduct`). The raw frontier category (`adapter`) remains available for ranking diagnostics but is NOT used for routing.

#### `refine`
Invoke `/yoke refine {item_id}` by reading and following `.agents/skills/yoke/refine/SKILL.md`, passing `{item_id}` as the argument.

#### `shepherd`
Invoke `/yoke shepherd {item_id}` by reading and following `.agents/skills/yoke/shepherd/SKILL.md`, passing `{item_id}` as the argument.

#### `conduct`
Invoke `/yoke conduct {item_id}` by reading and following `.agents/skills/yoke/conduct/SKILL.md`, passing `{item_id}` as the argument.

#### `advance`
Invoke `/yoke advance {item_id} implementation` by reading and following `.agents/skills/yoke/advance/SKILL.md`, passing `{item_id}` and `implementation` as arguments. This is the issue main-session implementation path — the scheduler routes issues at implementation-eligible statuses here instead of through `conduct`.

#### `polish`
Invoke `/yoke polish {item_id}` by reading and following `.agents/skills/yoke/polish/SKILL.md`, passing `{item_id}` as the argument.

#### `usher`
Invoke `/yoke usher {item_id}` by reading and following `.agents/skills/yoke/usher/SKILL.md`, passing `{item_id}` as the argument.

#### `wait`
This should not appear in the assignable Runnable table. If encountered, report:
```
Item {item_id} has next_step "wait" — it has unsatisfied dependencies.
Blocked by: {blocked_by list}
Reasons: {blocked_reasons list}

No dispatch possible. Resolve the blocking items first.
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
 --item-id "{item_id}" \
 --context "{\"next_step\":\"wait\",\"adapter\":\"{adapter}\",\"dispatched\":false,\"reason\":\"wait_encountered\",\"project\":\"{project}\"}"
```

Then stop without dispatching.

**Emit ChargeDecisionMade event** after successful dispatch:

```sh
yoke events emit \
 --name "ChargeDecisionMade" \
 --kind lifecycle \
 --type charge \
 --source-type skill \
 --severity INFO \
 --outcome completed \
 --item-id "{item_id}" \
 --context "{\"next_step\":\"{next_step}\",\"adapter\":\"{adapter}\",\"dispatched\":true,\"reason\":\"dispatched\",\"project\":\"{project}\"}"
```

Where:
- `{item_id}` is the dispatched item.
- `{next_step}` is the scheduler-derived dispatch action.
- `{adapter}` is the raw frontier adapter category (for diagnostics).
- `{project}` is the project scope.

Note: Non-dispatch exits (no runnable items, dry-run, unavailable explicit target, operator cancellation, unexpected `wait` next_step) emit `ChargeDecisionMade` in their respective steps before stopping.

## Events

This skill emits two structured events via the internal telemetry emit surface registered in `event_registry`:

- **FrontierComputed** — Emitted by the core Python frontier path (`runtime/api/domain/frontier_compute.py`) on every `compute_frontier()` call. No longer emitted by the charge skill directly.
- **ChargeDecisionMade** — Emitted on every terminal charge exit: after dispatch (step 6), on no runnable items (step 2), on `--dry-run` (step 3), when an explicit target is unavailable (step 4), on operator cancellation (step 5), and if an unexpected `wait` next_step is encountered during dispatch (step 6). Captures the selected item (if any), `next_step` (dispatch truth), `adapter` (raw frontier category), dispatch status, no-dispatch reason, and project.
