# Polish — Parse, Claim, Validate

## 1. Resolve identity and pin

```bash
ITEM_REF="{arg}"
ITEM_PIN_JSON=$(yoke workflows item get "$ITEM_REF" --json)
# ITEM_REF — public PREFIX-N for every item argument.
```

Require complete public identity, title, status, project, workflow id and
version. Read title/project through `yoke items get` if absent from the pin.
A failed, empty or malformed read halts with its actual error; do not turn it
into a missing-item or zero-lane fallback.

Read that exact immutable version:
```text
yoke workflows version get <workflow-id> <workflow-version> --json
```

Using `definition.stages` order, find the half-open
`definition.skill_bindings` interval containing the returned status. Require
`skill_id=polish`; retain its `from_stage_id` as `POLISH_ENTRY_STAGE` and
`through_stage_id` as `POLISH_THROUGH_STAGE`. Never route by workflow name.
No matching polish binding is `polish_binding_mismatch`: name the live stage
and owner and use the [shared handoff recipe](../shared/stage-handoff.md).

## 2. Claim — HARD GATE

Acquire before filesystem lane validation, context, diff review, tests, or
exploration. Claim before any status mutation. Stamp the session's mode:
```bash
yoke sessions touch --mode polish
yoke claims work acquire --item "$ITEM_REF" --reason polish_run
```

This claim-work operation is `claims.work.acquire`; it
**touches the session row in the same transaction**. The active session comes from ambient identity.
A `claim_conflict` stops immediately. Verify the returned claim/registered
holder belongs to that session before continuing:
```bash
yoke claims work holder-get --item "$ITEM_REF" --json
yoke sessions identity --json
```

If holder verification fails, halt and name the failed condition and acquire
recovery. Never construct a DSN or use a worktree-local control plane.

## 3. Validate lanes and activate

Use the existing registered lane set:
```bash
yoke item-worktrees list "$ITEM_REF" --json
yoke item-worktrees get "$ITEM_REF" --field path
yoke item-worktrees get "$ITEM_REF" --field branch
```

Retain project, every path/branch and count; a single lane also supplies
`WORKTREE_PATH`/`WORKTREE_BRANCH`. Multiple lanes supply
`WORKTREE_PATHS`/`WORKTREE_BRANCHES`; do not collapse them into a parent-ref
path or borrow one sibling's lane. Resolve `REPO_ROOT` from their owning
checkout and validate every path as an existing directory. Zero/empty rows,
failed reads or missing directories halt with the actual missing lane and
implementation/conduct re-entry recovery. Every file operation uses these
absolute lane paths.

Refresh the pin/version after claiming and recheck polish ownership.
Set `LIVE_STAGE` to its status. At `POLISH_ENTRY_STAGE`, select the unique
declared forward edge from `definition.transitions`, using
`definition.stages` order to exclude rework. Its target `NEXT_STAGE` must be
strictly before `POLISH_THROUGH_STAGE` and inside the interval.
No unique edge is `workflow_next_stage_ambiguous`; no working stage before
the boundary is `polish_segment_invalid`. Stop for workflow-owner repair or
declared-route selection; do not invent a stage.

`lifecycle.transition.execute` runs the target gates:
```bash
yoke lifecycle transition "$ITEM_REF" --from "$LIVE_STAGE" --to "$NEXT_STAGE" --reason "Polish started"
```

On resumed working stages, **skip the entry transition**. Refresh status after
success; require both this session's active work claim and a working stage
inside the polish interval before [context.md](context.md).
