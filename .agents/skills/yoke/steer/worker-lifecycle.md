# /yoke steer — worker lifecycle and frontier discipline

These rules bind `/yoke steer` launch behavior after one atomic steering
acquire has paired the coordinator's project seat and strategy-doc lock.
Workers never acquire or release either half. Do not defer these rules.

## 1. Encode dependency edges before frontier availability

Whoever files a batch of related items writes the `item_dependencies`
edges — or an explicit no-edges attestation — in the same action that
files them. Before launching a worker at a new item:

```text
yoke shepherd dependency-list PREFIX-N --json
```

Refuse to launch when a title-only related batch is already claimable
without edges or an attestation. A worker must never be sent at work the
frontier should not have offered.

## 2. Keep the frontier maxed out

Launch a worker promptly for every runnable unclaimed item in this
steering scope. Do not wait for the operator to pick. Nothing else
staffs: the fleet report names work that sat unpicked, and this seat is
what acts on it, using the launcher recipe below.

Surfaces are not exclusive. Each of `claude-cli`, `codex-cli`, and
`cursor-cli` hosts as many concurrent sessions as the work needs. Do
not invent a one-session-per-surface cap — nothing states one and no
mechanism enforces one. Staff every runnable unclaimed item. The bound
is that item set plus whether the chosen CLI surface is launchable
(preview in rule 3). Balance never withholds a launch.

Staff what this seat files in the same pass that files it, as soon as the
item is runnable. Do not wait for a report to name work created seconds
ago: the report exists for work this seat did not create, and an item it
just filed needs no discovery step. Filing and staffing are one action.

## 3. Launch CLI surfaces only

Steering-launched sessions use `claude-cli`, `codex-cli`, or
`cursor-cli`. Desktop surfaces only when the operator directs it or a
named exception scenario requires it.

Preview the chosen CLI surface before every launch. Pass that target
`--surface` explicitly; never the calling session's own surface. A
steering session commonly runs on a desktop surface that cannot create
sessions.

```text
yoke session-control launch preview --project {_project} --surface {_surface} --json
```

Read `launchable`, `rejection_codes`, and `eligible_relays`.
`claude-desktop` returns `launchable=false` with
`rejection_codes=["unsupported_surface"]`; `codex-cli` returns
`launchable=true` with relays and a version. Codes an agent meets:

- `unsupported_surface` — requested surface cannot create. Preview a
  CLI surface instead.
- `surface_disabled` — operator mark; staff onto the other CLI surfaces.
- `no_eligible_relay` — no live relay for that surface; try another CLI
  surface.

A refusal names the surface, not the item. Do not skip remaining work
because one surface refused.

Keep steady-state launches balanced across all three CLI surfaces. Deviate
only for a named live reason, such as a failing launch path or a capability
the item specifically needs, and return to balance when that reason expires.
The spread is diagnostic, not a quota: skew can hide a harness-specific
regression. The fleet report's launch-balance block shows the live count
per launchable surface on each machine. A surface absent from that line
cannot accept a launch — do not read a missing surface as zero.

Measure balance against live load; never assume it from the batch. Read those
counts before staffing, then allocate each launch so the counts it leaves
behind come out as level as they can. Leveling routes a launch onto the
least-loaded launchable surface; it never withholds one.

Never split a batch evenly across surfaces. An even split preserves whatever
skew is already there: six items sent two per surface onto a fleet already
running codex 5, claude 3, cursor 1 leaves codex 7, claude 5, cursor 3 — the
same skew, one size larger. Leveling that fleet sends most of the six to
cursor.

Allocation at launch is the only chance to get this right. Rebalancing
afterwards would mean killing live workers mid-item, so there is no second
pass that fixes a skewed batch.

## 4. Route one item through its pinned workflow, never via `/yoke do`

Before authoring the launch, read the pinned workflow and scheduler route:

```text
yoke workflows item get PREFIX-N --json
yoke charge schedule --project {_project} --item PREFIX-N --json
```

The launch prompt names exactly one item, the returned routed entrypoint, and
that workflow's remaining legs. One worker owns the item across those legs.
Work arriving in any workflow stays there; never convert or re-file it to make
it Dash-shaped. Chaining `/yoke do` duplicates the steerer-owned selection.

## 5. Workers self-end after their DONE message

After sending `DONE PREFIX-N <one-line summary>`, the worker must END its own
session. That non-destructive self-END is the canonical close: no lingering,
no re-tasking, and no routine termination by the steerer.

`yoke sessions terminate` is reserved for an unresponsive worker or explicit
cleanup. In those exceptional cases, resolve the full session id from the
launch that staffed the item, then terminate it:

```text
yoke sessions terminate {WORKER_SESSION_ID} --reason "PREFIX-N unresponsive cleanup"
```

Resolve `{WORKER_SESSION_ID}` from the launch that staffed the item
(`yoke session-control launch list --project {_project}` /
`yoke session-control launch get LAUNCH-ID`). No lingering. No re-tasking.

## 6. Every new item gets a fresh session

Never re-task an existing worker onto a different item. A new item is a
new `session_control.launch.create`.

## 7. Choose the model per item at launch

Default resolution: explicit `--model` on the launch > machine-config
`preferred_session_models` map > vendor default. Blank (or whitespace)
map values are unset and fall through to the vendor default. Override
per item when the work warrants — a heavier model for architecture,
migration, or high-risk items; a faster model for mechanical or
copy-level dashes. The override is the launch's explicit `--model`.
The resolved choice is recorded on the launch row.

```text
yoke session-control launch preview --project {_project} --surface {_surface} --list-models
```

## Launcher recipe

Preview is mandatory. Do not create until preview returns
`launchable=true` for the chosen CLI surface. The body is stdin. CLI
surface only. One item.

```text
printf '%s' "$BODY" | yoke session-control launch create \
  --project {_project} \
  --surface {_surface} \
  --item {ITEM} \
  --stdin \
  --idempotency-key "steer:{_project}:{ITEM}:{_surface}" \
  --model {_model} \
  --json
```

Managed `claude-*` launches are local-only per launch: Yoke disables Claude
Remote Control without changing the operator's normal Claude settings. The
display name is derived from `{ITEM}` plus its authoritative backlog title;
the instruction body never becomes a title or command-line argument.

Retain the returned `launch_id` and `deadline_at`. By that deadline, require
`state=succeeded` and a non-empty `registered_session_id`:

```text
yoke session-control launch get {LAUNCH_ID} --json
```

On `outcome_unknown` or a missed registration deadline, reconcile and retry:

```text
yoke session-control launch reconcile {LAUNCH_ID} --json
yoke session-control launch retry {LAUNCH_ID} --json
```

After repeated `relay_lease_expired` results on one surface, relaunch the item
on a different CLI surface and immediately file a field-note with the launch
ids and result codes.

`$BODY` parameterizes both its first line and its legs from the live route.
The steerer messages a worker with
`yoke say --item PREFIX-N --stdin`. The worker reports back with
`--session` only because the steerer is itemless (claim-less fallback).
No Yoke surface shortens a session id, so a short one did not come from Yoke: never pad, complete, or expand one by hand.

A worker's messages are substantive only. Every message costs this seat an
inbox row and a hand acknowledgement, so a worker sends one when a gate goes
red, it is blocked, its instruction conflicts with what it is seeing, it found
a defect outside its scope, its item reached a terminal state, or it needs a
decision. It never forwards progress output upward — a percentage, an
elapsed-time poll, a watcher heartbeat, a "still green" note. Those belong in
the worker's own visible output; this seat reads liveness from
`yoke watch fleet`, and the send path refuses a progress tick as
`body_not_substantive`.

```text
{ROUTED_ENTRYPOINT}

Single-item mandate (steering): acquire the PREFIX-N work claim as your FIRST action, then execute only PREFIX-N through {ROUTED_LEGS}. Do NOT create or dispatch any deployment run — the orchestrator batches deploys. Message the orchestrator ONLY for substantive updates — a red gate and what failed, a blocker, a conflict with this instruction, a defect outside your scope, a decision you need. NEVER send progress: no percentages, elapsed-time polls, watcher heartbeats, or "still green" notes; relay those in your own output instead. When those legs are complete, message the orchestrator (printf %s "DONE PREFIX-N <one-line summary>" | yoke say --stdin --session {STEERER_SESSION_ID}) and END your session — do not pick up further work, do not chain into other items. If your claim is swept mid-work, reacquire and continue.
```

Author the routed variants side by side from the pinned `workflow_id` and
`charge.schedule.next_step`, never from memory:

- Dash: `/yoke dash PREFIX-N`; one Dash leg through its merge/evidence close.
- Issue: `/yoke refine PREFIX-N` to `refined-idea`, then
  `/yoke advance PREFIX-N implementation`, implementation and `/yoke polish`
  per the live bindings, then that binding's merge boundary.
- Blitz: `/yoke blitz PREFIX-N` after the strategy-document handoff.
- Epic: the `/yoke shepherd`, `/yoke conduct`, and `/yoke usher` chain named
  by the live bindings.

At every live stage, re-read `yoke workflows item get PREFIX-N` and follow its
binding. If the next bound leg would create a deployment run, stop at the
merge or release boundary and report; the steerer performs batch delivery.
One worker remains responsible for the one item throughout.

When a worker is blocked on an upstream item, stamp parked before going
quiet so the stale-alive probe leaves it alone:

```text
yoke sessions touch --mode parked --reason "waiting on PREFIX-N"
```

That write persists until the worker stamps a working mode
(`yoke sessions touch --mode dash`). Reporting and control-plane reads
do not unpark.

Use this recipe for every launch, whether the item just became runnable
or the fleet report named it as available. There is no second staffing
path: every launch is item-bound and CLI-only, and this seat composes it.

When same-surface worker failures carry a vendor-side signature, disable
that surface with `yoke session-control surface-policy disable` and staff
onto the other harnesses. Do not mark unclassified failures. Re-enable
only after one successful canary launch. See the Surface disable marks
section in `SKILL.md`.
