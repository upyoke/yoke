# /yoke charge steps 4–6 — select, confirm, dispatch

## 4. Select the target item

If `--item PREFIX-N` was passed:
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

## 5. Confirm with operator

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
- "Pick a different item (specify PREFIX-N)"
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

## 6. Dispatch to downstream skill

Based on the confirmed item's `next_step` field, dispatch as follows. The
`next_step` value is the dispatch truth from the pinned workflow binding. The
raw frontier category (`adapter`) remains available for ranking diagnostics
but is NOT used for routing.

### `refine`
Invoke `/yoke refine {item_id}` by reading and following `.agents/skills/yoke/refine/SKILL.md`, passing `{item_id}` as the argument.

### `shepherd`
Invoke `/yoke shepherd {item_id}` by reading and following `.agents/skills/yoke/shepherd/SKILL.md`, passing `{item_id}` as the argument.

### `conduct`
Invoke `/yoke conduct {item_id}` by reading and following `.agents/skills/yoke/conduct/SKILL.md`, passing `{item_id}` as the argument.

### `advance`
Invoke `/yoke advance {item_id} implementation` by reading and following `.agents/skills/yoke/advance/SKILL.md`, passing `{item_id}` and `implementation` as arguments. This is the issue main-session implementation path — the scheduler routes issues at implementation-eligible statuses here instead of through `conduct`.

### `dash`
Invoke `/yoke dash {item_id}` by reading and following `.agents/skills/yoke/dash/SKILL.md`, passing `{item_id}` as the argument. The stored instruction is the complete scope; Dash runs survey, worktree, verification, merge, and evidence in this session.

### `blitz`
Invoke `/yoke blitz {item_id}` by reading and following `.agents/skills/yoke/blitz/SKILL.md`, passing `{item_id}` as the argument. Blitz executes the item's single linked execution strategy document.

### `polish`
Invoke `/yoke polish {item_id}` by reading and following `.agents/skills/yoke/polish/SKILL.md`, passing `{item_id}` as the argument.

### `usher`
Invoke `/yoke usher {item_id}` by reading and following `.agents/skills/yoke/usher/SKILL.md`, passing `{item_id}` as the argument.

### `wait`
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

