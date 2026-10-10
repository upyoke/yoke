# Charge: Schedule and frontier

Stamp the mode, then read the claim-aware schedule:

```sh
yoke sessions touch --mode charge
yoke charge schedule [--project P] [--item PREFIX-N] --wip-cap <wip_cap> --json
```

Omit project/item flags when argless to retain workspace-home scope. Use the
router's WIP default unless overridden. Nonzero exit: show the error and stop.
Read the command's help for the full result contract. The engine emits
`FrontierComputed`; do not emit it again.

## Present the frontier

Filter `ranked_steps` to `unclaimed`, `claimed_by_self`, `claimed_by_stale`.
Exclude `claimed_by_other_live`; this is the assignability contract in
`yoke_core.domain.scheduler_types.is_assignable_claim_state`.

Show project and WIP active/cap plus a ranked Runnable table with columns
number, item, title, status, adapter, priority, unblocks. Report the count held
by other live sessions separately; they still exist on the ranked frontier.
For `blocked_steps`, show item/title/status/blocker and unsatisfied gate/rationale:
prefer `gate_evaluations` (`gate_point`, `rationale`) over `blocked_reasons`.
Show `frozen_steps` count as excluded.

If all ranked work was held-live, say nothing is assignable, rather than calling
the frontier empty. If `selected_step` is empty and `runnable_elsewhere` exists,
show the elsewhere note and stop. If both are empty, report no runnable work and
suggest `/yoke feed` or `/yoke doctor`. Emit the `no_runnable_items` decision
through [events.md](events.md) before each no-dispatch stop.

## Dry run

With `--dry-run`, show “dry-run mode — no dispatch”, emit `dry_run` through
[events.md](events.md), and stop without confirmation or dispatch.
Otherwise continue with [select-and-dispatch.md](select-and-dispatch.md).
