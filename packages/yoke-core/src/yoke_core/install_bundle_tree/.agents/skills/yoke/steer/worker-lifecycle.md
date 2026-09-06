# /yoke steer — worker lifecycle and frontier discipline

These rules bind `/yoke steer` launch behavior after one atomic steering
acquire has paired the coordinator's project seat and strategy-doc lock.
Workers never acquire or release either half. Do not defer these rules.

## 1. Encode dependency edges before frontier availability

Whoever files a batch of related items writes the `item_dependencies`
edges — or an explicit no-edges attestation — in the same action that
files them. Before launching a worker at a new item:

```text
yoke items dependency list PREFIX-N --json
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
- `machine_at_capacity` — every eligible machine is already running its
  lane cap, counting live sessions plus launches assigned there and not
  yet registered. The refusal names each full machine's lanes, free
  memory, load, cores, and where its cap came from. Wait for a landing to
  free a lane, raise `max_worker_lanes` under settings in
  `~/.yoke/config.json` on that machine, or pass `--machine` to place the
  launch on a machine with room. Do not retry the same placement: the cap
  is a memory fact about that box, not a transient race.
- `machine_access_denied` — no eligible machine is one this actor may use;
  `placement_reason` says why per machine.

A refusal names the surface, not the item. Do not skip remaining work
because one surface refused.

**Do not pick the machine.** A launch naming no `--machine` is placed for
you: among the machines this actor may use that offer the surface, the one
with the most headroom wins, and the requester's own machine wins a tie.
Headroom is the lowest meter that machine publishes for the surface — the
soonest wall is the one a launch can hit. `placement_reason` names the winner,
the readings it beat and the deciding meter; `machine_candidates` carries those
per machine. Both land on the launch row. Pass `--machine` only to override.

Choosing the SURFACE is still yours.
Allocate by headroom, not by leveling counts. Read the headroom table in the
fleet report: keep one session on every surface above 100% so each harness
stays exercised, then send the rest to the surface with the most headroom and
run it down. Level counts only when headrooms are comparable, and avoid a
surface under 100% for long items. There is no per-surface session cap; a
surface absent from the launch-balance line cannot accept one at all.

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

## 5. Workers self-end after their DONE report

After its `DONE PREFIX-N <one-line summary>` report, the worker must END its
own session. That non-destructive self-END is the canonical close: no
lingering, no re-tasking, and no routine termination by the steerer. Every
worker sends the report deliberately with `yoke say --steering`, before
releasing any claim it still holds. Ending a turn sends no Fleet message. One
terminal report per session and item reaches this seat once, so a reworded
retry deduplicates instead of arriving twice.

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

## 7. Choose model, effort, and context per item at launch

Resolve each knob independently: its explicit launch flag > the value
advertised by the machine the launch was placed on > the vendor default. The
target machine owns these defaults because it owns the provider account and
installed models, never this seat's config. Context uses that machine's scalar
`preferred_session_models` selector and effort uses its additive
`preferred_session_reasoning_efforts` map. Blank values are unset.
Override per item when risk warrants. Preview shows the raw request and its
effective selection; the launch retains both, and the session shows the ask
beside served facts. `--list-models` reports local maps; preview reads remote defaults.
Claude accepts model, effort, and the 1M context tier; Codex accepts model and
effort but no explicit context window; Cursor accepts all three in its
parameterized model selector. Preview refuses unsupported knobs with a
harness-specific code. A provider rejection becomes `model_combo_unsupported`
with bounded CLI detail: choose another listed combination and create a new
launch. Never remove flags and silently fall back to vendor defaults.

## 8. Tell a worker to survey a neighbour lane with Git, not prose

When two live items share a file, the worker that edits second needs to
see the first one's uncommitted hunks. Say so with the command it can
actually run: read-only Git inspection of another item's live worktree is
allowed, so the survey is a direct read of the neighbour's tree.

```text
yoke claims work holder-get --path <shared/path>
git -C /abs/path/to/.worktrees/<neighbour-branch> status --short
git -C /abs/path/to/.worktrees/<neighbour-branch> diff -- <shared/path>
```

One plain Git call per invocation. `status`, `diff`, `log`, `show`,
`ls-files`, `ls-tree`, `rev-parse`, `blame`, `describe`, and `shortlog`
are allowed with any arguments; `branch`, `remote`, and `config` only in
their listing form, with no positional argument. Redirection, chaining,
and `--output` are refused because they can write through an allowed
verb, as is every state move in that lane (`checkout`, `switch`, `reset`,
`restore`, `stash`, `clean`, `add`, `commit`, `merge`, `rebase`,
`cherry-pick`, `apply`, `worktree`). Reading a neighbour's files with
`cat`, `sed`, `rg`, or `Read` is still refused; the content route is the
shared object store from the main checkout,
`git -C <main-checkout> show <rev>:<path>`.

A survey is not authority to edit the shared file in the neighbour's
lane. The worker edits in its own lane and coordinates with the holder
the first command named.

## Launcher recipe

Preview is mandatory. Do not create until preview returns
`launchable=true` for the chosen CLI surface. CLI surface only. One item.
`session_control.launch.create` composes the canonical single-item mandate
server-side from the item ref and the charge-schedule route. Every worker
reports deliberately with `yoke say --steering`. The mandate carries no
session id: the report is addressed to the steering ROLE. Do not hand-assemble
the worker body.
Optional extras append after that mandate via `--stdin`. Use
`--raw-instructions` only for a non-standard full body.

```text
yoke session-control launch create \
  --project {_project} \
  --surface {_surface} \
  --item {ITEM} \
  --idempotency-key "steer:{_project}:{ITEM}:{_surface}:{_model}:{_effort}:{_context}" \
  --model {_model} \
  --reasoning-effort {_effort} \
  --context-window {_context} \
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

If `native_launch_phase` is `spawn_started` or `spawn_alive`, the first native
process still owns the launch. Wait through `deadline_at`; reconciliation
refuses with `native_process_alive`, and retry reattaches to that attempt
instead of starting a duplicate. After the deadline containment has run, or
when no live phase is recorded, reconcile and retry:

```text
yoke session-control launch reconcile {LAUNCH_ID} --json
yoke session-control launch retry {LAUNCH_ID} --json
```

After repeated `relay_lease_expired` results on one surface, relaunch the item
on a different CLI surface and immediately file a field-note with the launch
ids and result codes.

The server emits this single-item mandate (steering) shape — claim first,
execute only that item through the routed legs, no deployment run, report then
END. Every worker gets the `yoke say --steering` DONE step in the same place.
The steerer messages a worker with `yoke say --item PREFIX-N --stdin`. The
worker reports back with
`yoke say --steering`, which addresses the ROLE rather than this seat: the
server resolves it at delivery to whichever seat covers the worker's item,
and parks it for the next seat when none is live. So a worker launched by a
seat that later stops still reports to whoever holds the scope, and this seat
inherits that mail on acquire instead of chasing it. The send says which of
those happened: its steering recipient reports `awaiting_seat` with the scope
it is queued for, or `delivered` naming the seat, so a parked report never
reads as a message that went nowhere. Never put a session id in
a mandate, and never pad, complete, or expand one by hand — no Yoke surface
shortens a session id, so a short one did not come from Yoke.

A worker's messages are substantive only. Every message costs this seat an
inbox row and a hand acknowledgement, so a worker sends one when a gate goes
red, it is blocked, its instruction conflicts with what it is seeing, it found
a defect outside its scope, its item reached a terminal state, or it needs a
decision. It never forwards progress output upward — a percentage, an
elapsed-time poll, a watcher heartbeat, a "still green" note. Those belong in
the worker's own visible output; this seat reads liveness from
`yoke watch fleet`. Message another session only for something it would act
on; that is coordination advice, not a send-path refusal. Ending a turn sends
no Fleet message. Launch origin does not change that boundary: every worker
deliberately sends terminal and other actionable reports with `yoke say
--steering`.

Every launched worker, whatever its origin, is a headless command, so the
mandate also tells it what a merge-queue landing is. It cannot be prompted
again inside its own turn and it cannot outlive the landing either — the turn
is capped well below one — so `yoke merge item` arms the landing for such a
worker and returns, whatever the worker passed. Seven items in one night
landed their branches and sat at `reviewing-implementation` waiting for a
re-entry nobody could make; the control-plane landing notice is what closes
that gap, and it re-enters the worker for close-out. The mandate therefore
tells a launched worker to report the pull request, stop deliberately, and
re-run the same command when the notice arrives.

```text
{ROUTED_ENTRYPOINT}

Single-item mandate (steering): acquire the PREFIX-N work claim as your FIRST action, then execute only PREFIX-N through {ROUTED_LEGS}. Do NOT create or dispatch any deployment run — the orchestrator batches deploys. Message the orchestrator ONLY for substantive updates — a red gate and what failed, a blocker, a conflict with this instruction, a defect outside your scope, a decision you need. NEVER send progress: no percentages, elapsed-time polls, watcher heartbeats, or "still green" notes; relay those in your own output instead. When those legs are complete, message the orchestrator (`printf %s "DONE PREFIX-N <one-line summary>" | yoke say --stdin --steering`) and END your session — do not pick up further work, do not chain into other items. Send that report before releasing any claim you still hold; after close-out already released it, `--steering` resolves from the item you last held in this session. If your claim is swept mid-work, reacquire and continue.

You are a headless command that cannot be prompted again, so a merge-queue landing is not yours to wait out: it outlasts your turn, and a wait that dies with the turn leaves the branch landed and the item open. Your merge arms the landing and returns landing_pending=true with the pull request named, whether or not you passed --wait. That is the handoff, not a failure. Report the pull request, stop deliberately, and say you are waiting on landing. The control-plane landing notice wakes you: re-run the same `yoke merge item` command then and it completes close-out. A stopped landing arrives the same way and names its recovery (usually rebase, re-run the verification gate, re-run the command); a stale server landing record names its last refresh and repair step. Never replace either with local GitHub polling, and never report a landing you did not read. A separate check uses `yoke github merge-queue readiness PREFIX-N --json`: the named queue-entry state decides whether null arming was consumed or cleared.

Ending a turn sends no Fleet message. Send the DONE report deliberately with `yoke say --steering` — lead with `DONE <item> <one-line summary>`, then what landed, what is blocked, and what you need — before ending the session.
```

The server parameterizes that shape from the pinned `workflow_id` and
`charge.schedule.next_step`. Workers still re-read the live binding:

- Dash: `/yoke dash PREFIX-N`; one Dash leg through its merge/evidence close.
- Task: `/yoke advance PREFIX-N implementation`, then the bound Dash close-out
  records merge-free floor evidence; no worktree, QA, merge, or deployment leg.
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

When a worker enters any intentional external wait — blocked on an
upstream item, waiting on operator sign-in, waiting on an approval, or
holding at an explicit operator instruction — stamp parked with a
concrete reason before going quiet, so the stale-alive probe leaves it
alone:

```text
yoke sessions touch --mode parked --reason "waiting on PREFIX-N"
yoke sessions touch --mode parked --reason "waiting on operator sign-in"
yoke sessions touch --mode parked --reason "waiting on approval: <what>"
```

That write persists until the worker stamps a working mode
(`yoke sessions touch --mode dash`) once the wait clears. Reporting the
wait, or knowing its reason, is not the state change and does not unpark
— only the mode stamp does, and control-plane reads never unpark either.

Parking also shields what the worker holds. A QA plan execution whose owner
is parked is not reaped as stale, so a walker told to hold keeps its mission
rather than losing it to the sweep. That shield lasts as long as the session
does: if the park outlives the session — a sleep, a reload, an end — the
sweep settles the execution and stamps its capture with an error verdict.
The Test Machine still holds the walk's state, and the walker re-enters with
the `yoke qa plan run ... --continue-mission` command its next
`yoke qa mission host-command` refusal names. Tell a held walker to continue
rather than to re-run the plan; an ordinary run resets the host.

Use this recipe for every launch, whether the item just became runnable
or the fleet report named it as available. There is no second staffing
path: every launch is item-bound and CLI-only, and the server composes it.

When same-surface worker failures carry a vendor-side signature, disable
that surface with `yoke session-control surface-policy disable` and staff
onto the other harnesses. Do not mark unclassified failures. Re-enable
only after one successful canary launch. See the Surface disable marks
section in `SKILL.md`.
