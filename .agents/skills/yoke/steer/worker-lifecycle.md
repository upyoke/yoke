# /yoke steer — worker lifecycle and frontier discipline

These rules bind `/yoke steer` launch behavior after one atomic steering
acquire has paired the coordinator's project seat and strategy-doc lock.
Workers never acquire or release either half. Do not defer these rules.

## A quiet worker is not an absent worker

- **A worker in any intentional external wait stamps parked before going
  quiet** — blocked on an upstream item, waiting on operator sign-in,
  waiting on an approval, or holding at an explicit operator instruction —
  with a concrete reason:
  `yoke sessions touch --mode parked --reason "waiting on PREFIX-N"`. That
  write persists. Reporting the wait, reading the control plane, heartbeat,
  message ack, failed wakes, and tool calls do not unpark. An accepted
  UserPromptSubmit that stamps the turn running clears the previous parked
  mode and reason. A later explicit re-park persists: the parked write
  advances turn_posture_at, so a delayed accepted prompt observed before
  that write cannot clear it. A stale start observation does not unpark.
  Stamp a working mode when continuing by
  choice (`yoke sessions touch --mode dash`). A genuinely
  parked, in-flight, or merge-queue-landing worker is not terminated or
  restaffed for being quiet; verify the recorded reason, then resume it
  once its blocker actually clears.

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

## 5. Workers self-end after their DONE report — once the item is done

A worker's legs are complete when its item reaches a terminal status, not when
its branch merges. A merge that lands at the pinned release wait keeps the
worker's claim and parks its session on that wait, and the worker stays the
owner through delivery and post-deploy validation. Do not read a parked
release-wait holder as a worker that forgot to finish, do not ask it to
release, and do not terminate it for being quiet: the deployment wake re-enters
it when its delivery clears or a QA stage needs it, and it closes out and
reports then. A holder that goes quiet WITHOUT that park is treated as gone —
the stale sweep reclaims it and mails this seat a named hand-off for the
orphaned item, which is staffing work, not a notification to file.

After its `DONE PREFIX-N <one-line summary>` report, the worker must END its
own session. That non-destructive self-END is the canonical close: no
lingering, no re-tasking, and no routine termination by the steerer. Every
worker sends the report deliberately with `yoke say --steering`, before
releasing any claim it still holds. Ending a turn sends no Fleet message. The
PREFIX-N in the heading is the report identity and must name held or released
work. One report per work leg reaches this seat once, so a reworded retry of the
same completion deduplicates instead of arriving twice. A worker you resume
reports its next completion as its own leg, delivered rather than collapsed,
whether the resume hands it a fresh claim or leaves an unfinished lane held.
Never ask a worker to release a live lane just to be heard. A worker resumed
WITHOUT its session ending — told "also do X" in the same episode, on the same
claim — is the one shape that still collapses; it is told so loudly and reports
that completion as a substantive update instead.

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

Which model and effort each item asks for — the three kinds of work, the
operator's per-surface routing preference, Cursor's Grok-first rule and what
counts as a confirmed empty pool, adopting a new model, and why a resume keeps
its selection — is [`model-selection.md`](model-selection.md). Read it before
naming a model. The mechanics of how a named knob resolves are here.

Resolve each knob independently: its explicit launch flag > the value
advertised by the machine the launch was placed on > the vendor default. The
target machine owns these defaults because it owns the provider account and
installed models, never this seat's config. Context uses that machine's scalar
`preferred_session_models` selector and effort uses its additive
`preferred_session_reasoning_efforts` map. Blank values are unset.
Override per item when risk warrants. Preview shows the raw request and its
effective selection; the launch retains both, and the session shows the ask
beside served facts. `--list-models` reports local maps; preview reads remote defaults.
Preview also ranks each machine by the meter the requested model actually
bills to, and names that pool's own quota under `REQUESTED MODEL POOL`.
Claude accepts model, effort, and the 1M context tier; Codex accepts model and
its advertised effort levels but no explicit context window. Cursor preserves
the exact native selector: effort resolves to an advertised variant, and an
explicit context request requires that variant's native label to name the
window. Never append bracket parameters to a published Grok selector or infer
its window from a Claude model. Preview refuses conflicting or unsupported
combinations before spawning, with a harness-specific code and recovery.
A provider rejection becomes `model_combo_unsupported`
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
`launchable=true` for the chosen CLI surface. CLI surface only. Composed
mandates require `--item`; `session_control.launch.create` composes the
canonical single-item mandate server-side from that ref and the
charge-schedule route. Itemless launches use `--raw-instructions` with a
nonempty `--stdin` body and skip item lookup, terminal-item checks, and
item-derived naming. Every worker reports deliberately with
`yoke say --steering`. The mandate carries no session id: the report is
addressed to the steering ROLE. Do not hand-assemble the worker body.
Optional extras append after a composed mandate via `--stdin`.

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

Itemless raw-instructions (explicit body, no `--item`):

```text
yoke session-control launch create \
  --project {_project} \
  --surface {_surface} \
  --raw-instructions --stdin \
  --idempotency-key "steer:{_project}:raw:{_surface}:{_model}:{_effort}:{_context}" \
  --model {_model} \
  --reasoning-effort {_effort} \
  --context-window {_context} \
  --json
```

Managed `claude-*` launches are local-only per launch: Yoke disables Claude
Remote Control without changing the operator's normal Claude settings. A
composed launch's display name is derived from `{ITEM}` plus its
authoritative backlog title; the instruction body never becomes a title or
command-line argument. Itemless launches omit that name.

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
The single-recipient `yoke say --item PREFIX-N --stdin` form is insufficient
for a substantive peer request because it does not copy steering.
The steerer sends a substantive peer request with `yoke say --item PREFIX-N
--steering --stdin`, addressing the worker and copying the relevant steering
seat because anchors union. A recipient replies to the exact original
requesting session and copies steering with `yoke say --session
EXACT-REQUESTING-SESSION-ID --steering --stdin`; when it holds no applicable
item, it uses explicit `--steering-scope '{"project_id": N}'` in place of
`--steering`. Never reconstruct a session id, and never send a refusal only to
steering while leaving the requester uninformed. The worker's terminal report
uses `yoke say --steering`, which addresses the ROLE rather than this seat: the
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

Acknowledging a peer request records receipt only. It does not accept the
request or promise implementation; acceptance or refusal is a substantive
reply to the requester with steering copied as above.

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

The same mandate names where those legs actually end. A worker whose merge
landed at a pinned release wait read "when those legs are complete" as
complete: twelve items in one night were reported and left unowned before
their delivery ran, against four whose workers parked and held. The close-out
keeps the claim and parks the session on that wait, and the mandate names the
boundary so the worker does not undo it.

The same mandate names the opposite failure, because a launched turn is the
whole life of every command it starts. When the harness moves a long command
to a background task, the child keeps running; a worker that read that
hand-back as completion ended its turn and killed the merge it was holding,
twice in one night, reporting success with no verdict recorded. The mandate
therefore tells the worker to continue the handed-back call until it exits,
and to stop early only for a command-handed wait or the taught local-check interrupt.

```text
{ROUTED_ENTRYPOINT}

Single-item mandate (steering): acquire the PREFIX-N work claim as your FIRST action, then execute only PREFIX-N through {ROUTED_LEGS}. Do NOT create or dispatch any deployment run — the orchestrator batches deploys. Message the orchestrator ONLY for substantive updates — a red gate and what failed, a blocker, a conflict with this instruction, a defect outside your scope, a decision you need. NEVER send progress: no percentages, elapsed-time polls, watcher heartbeats, or "still green" notes; relay those in your own output instead. For a substantive peer request or reply, address the intended worker/session AND copy relevant steering using union recipient flags (`--item PREFIX-N --steering`, or an exact listed `--session SESSION-ID --steering`; use explicit `--steering-scope '{"project_id": N}'` when you hold no applicable item). Reply to the original requesting session for acceptance, refusal, scope conflict, blocker, or decision; never send a rejection only to steering. Acknowledgement records receipt, not acceptance or implementation. When those legs are complete, message the orchestrator (`printf %s "DONE PREFIX-N <one-line summary>" | yoke say --stdin --steering`) and END your session — do not pick up further work, do not chain into other items. Send that report before releasing any claim you still hold; after close-out already released it, `--steering` resolves from the item you last held in this session. The PREFIX-N in the DONE heading is the report identity and must name work this session holds or released. If your claim is swept mid-work, reacquire and continue.

A merge that lands your item at its pinned release wait is a completed merge that is NOT a finished item: the delivery still has to run and its post-deploy validation still has to be walked before the item reaches done. That close-out therefore keeps your work claim and parks your session with the wait named, and you keep both. Do NOT release the claim and do NOT end your session there — report what landed in your own output, say you are waiting on delivery, and stop deliberately. The deployment wake re-enters you when your delivery clears or its QA stage needs you; re-run the same `yoke merge item` command with --result and --verification then, and it finishes the close-out. Only once the item reaches done do you send the DONE report and end. A release-wait owner that goes quiet without that park is treated as gone and its item is handed to steering, so the park is what keeps the item yours.

You are a headless command that cannot be prompted again, so a merge-queue landing is not yours to wait out: it outlasts your turn, and a wait that dies with the turn leaves the branch landed and the item open. Your merge arms the landing and returns landing_pending=true with the pull request named, whether or not you passed --wait. That is the handoff, not a failure. Report the pull request, stop deliberately, and say you are waiting on landing. The control-plane landing notice wakes you: re-run the same `yoke merge item` command then and it completes close-out. A stopped landing arrives the same way and names its recovery (usually rebase, re-run the verification gate, re-run the command); a stale server landing record names its last refresh and repair step. Never replace either with local GitHub polling, and never report a landing you did not read. A separate check uses `yoke github merge-queue readiness PREFIX-N --json`: the named queue-entry state decides whether null arming was consumed or cleared.

A tool call that outlives its yield is still running. When your harness moves a long command to a background task or hands back a continuation handle, that is the harness handing the call back, not an interruption: the child and whatever it is waiting on are still alive. Continue that same call through your harness's continuation surface until it exits and you have read its outcome — reading the background task's output continues the call, and only ending the turn kills the watcher and the child it was holding, which lands as a killed capture with no recorded verdict. Never start a second invocation beside a live one; re-run only once the first process is verifiably gone. Stop before a command finishes only where the command itself handed the wait off — a merge that returned landing_pending has its landing notice — or, as the explicitly taught exception, when a *local* test check on a project with declared CI has already exceeded about one minute: interrupt that test process cleanly, keep the capture as incomplete, commit, and continue the selection on that project's CI. Do not interrupt a CI-routed watcher, a machine-specific diagnostic, or a local run on a project without CI, and do not background the slow local selection to keep waiting.

Ending a turn sends no Fleet message. Send the DONE report deliberately with `yoke say --steering` — lead with `DONE PREFIX-N <one-line summary>` naming work this session holds or released, then what landed, what is blocked, and what you need — before ending the session.
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

The release wait is the one such wait the server stamps for the worker:
`yoke merge item` parks the merging session itself when its close-out lands at
the pinned release wait, because a retention that depended on the worker
remembering was the retention being lost. That park is what spares its claim
from the stale sweep, which reports a spared owner as `release_wait_owner`.

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
