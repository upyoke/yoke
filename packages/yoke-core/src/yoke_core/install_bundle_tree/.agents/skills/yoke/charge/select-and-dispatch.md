# Charge: Select, confirm and dispatch

## Select

An explicit `--item` must be in the assignable Runnable table. If held-live,
report `claimed_by_other_live`; otherwise inspect blocked/frozen/not-found
buckets and report the reason. Emit `requested_item_unavailable` with its bucket
through [events.md](events.md), then stop. Without an explicit target choose the
first assignable ranked item, matching `selected_step` when present; an empty
table returns to frontier's no-runnable branch.

## Confirm

Require nonempty `entrypoint` before confirmation. Show selected public ref,
title, status, adapter, `next_step` and exact action/entrypoint. Ask:

- Yes, dispatch to {entrypoint}
- Pick a different item (specify PREFIX-N)
- Cancel — do not dispatch

For a different item, validate assignability and repeat confirmation. Cancel
emits `operator_cancelled` through [events.md](events.md), then stops.

## Dispatch

Read and execute the confirmed returned entrypoint's skill, passing its
arguments unchanged. The scheduler uses the same binding-derived mapping as
launch mandates; never reconstruct a route from the adapter category.

Absent/null entrypoint on a non-wait step stops as `entrypoint_unavailable`,
naming item and next step. Recover by reading the pin and definition, then
refreshing against a serving build that exposes entrypoint:

```sh
yoke workflows item get PREFIX-N --json
yoke workflows version get <workflow> <version> --json
yoke charge schedule --item PREFIX-N --json
```

An older response's omission is a diagnosed refusal, never an invented route.
If `next_step=wait` appears, show unsatisfied `blocked_by`/`blocked_reasons`,
report no dispatch possible, emit `wait_encountered` and stop.
After successful downstream dispatch, emit `dispatched` through
[events.md](events.md). Downstream skills set their own session mode.
