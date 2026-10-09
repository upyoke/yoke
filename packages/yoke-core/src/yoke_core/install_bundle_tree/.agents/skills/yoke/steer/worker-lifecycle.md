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
- **An exited worker between turns is normal, not dead.** A headless worker
  runs one native turn at a time: its process exits when the turn ends, and
  the next message resumes it from its transcript in a new process. The
  fleet report says which state a quiet holder is in, and none of them is a
  reason to terminate:
  - *idle, process running — message it*: the native is alive; message it.
  - *idle, process exited — message it to resume from transcript*: send the
    message; that is the resume.
  - *resuming now*: a wake started after the recorded exit; let it start.
  Terminate only with evidence the worker cannot resume — a stranded
  session, a resume that died, or no answer after a resume that delivered.
  `yoke sessions terminate` refuses a session a wake is resuming as
  `TERMINATION_RESUME_IN_FLIGHT`; read the refusal before overriding it.

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
what acts on it, using the [launcher recipe](worker-launch.md).

Surfaces are not exclusive. Each of `claude-cli`, `codex-cli`, and
`cursor-cli` hosts as many concurrent sessions as the work needs. Do
not invent a one-session-per-surface cap — nothing states one and no
mechanism enforces one. Staff every runnable unclaimed item. The bound
is that item set plus whether the level has an option with capacity
(preview in rule 3). Balance never withholds a launch.

Staff what this seat files in the same pass that files it, as soon as the
item is runnable. Do not wait for a report to name work created seconds
ago: the report exists for work this seat did not create, and an item it
just filed needs no discovery step. Filing and staffing are one action.

## 3. Launch CLI surfaces only

Steering-launched sessions use `claude-cli`, `codex-cli`, or
`cursor-cli`. Desktop surfaces only when the operator directs it or a
named exception scenario requires it.

Preview every launch at the level judged under rule 7. Level options name CLI surfaces, so a level
launch never lands on the desktop surface a steering session commonly runs
on. An operator override that names `--surface` must name a CLI surface,
never the calling session's own.

```text
yoke session-control launch preview --project {_project} --level {_level} --json
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
- `level_no_capacity` — no option of the level can launch anywhere; the
  refusal names each option and the pool or rule that blocked it. Relaunch
  at another level if the work allows, or wait for the named reset.
- `level_unknown` — the project reads no such level; it lists the ones it
  does.

A refusal names the surface, not the item. Do not skip remaining work
because one surface refused.

**Do not pick the machine or the surface.** A level launch is placed for
you: every option of the level is weighed on every machine this actor may use,
against only the quota pools that option's model draws on, and the spread and
headroom rules choose. `placement_reason` names the winner and why;
`level_placement` carries every option, machine, and pool it read. Both land
on the launch row. The fleet report's **levels** block is that same dry run
for every level, with live workers per surface: read it to see which levels
have capacity before naming one. Pass `--machine` only to narrow placement,
and `--surface` only for an operator override. There is no per-surface
session cap.

## 4. Route one item through its pinned workflow

Before authoring the launch, read the pinned workflow and scheduler route:

```text
yoke workflows item get PREFIX-N --json
yoke charge schedule --project {_project} --item PREFIX-N --json
```

The launch prompt names exactly one item, the returned routed entrypoint, and
that workflow's remaining legs. One worker owns the item across those legs.
Work arriving in any workflow stays there; never convert or re-file it to make
it Dash-shaped. The worker executes only its assigned item; steering owns selection.

## 5. Workers self-end after their DONE report — once the item is done

A worker's legs are complete when its item reaches a terminal status, not when
its branch merges. A merge that lands at the pinned release wait keeps the
worker's claim and parks its session on that wait, and the worker stays the
owner through delivery and post-deploy validation. Do not read a parked
release-wait holder as a worker that forgot to finish, do not ask it to
release, and do not terminate it for being quiet: the deployment wake re-enters
it when a QA stage needs it or its own item-scoped QA clears. That wake reaches
only a natively wakeable surface. A holder on a surface whose wake authority
is operator (a desktop app) is never resumed by Yoke — its close-out block says
so — so when its stage opens, ask its operator to open that chat and type, or
re-enter it yourself. A holder whose item owes delivery nothing needs no
re-entry at all: delivery closes the item. Once that
member's scoped QA passes, is waived, or is explicitly discharged by
`post_deploy_no_obligation`, a selected flow without run QA or run approval closes
that final member after its own final production QA clears, even while
sibling QA keeps the run executing. Run QA or run approval holds all final members
through every item gate, shared gate, and run success. Membership alone is not
what closes a member: only a run of its own selected flow, or another
project's run that recorded a bound source for its project, has that
authority, and its success stamps the delivery evidence itself — no holder
re-runs merge to record it. A run reads succeeded only after every cleared
member has closed: until then it stays executing and settling, a refusal or
interruption leaves it there with the remaining members' claims and lanes
kept, and re-driving `status succeeded` replays settlement. A final member
with unanswered post-deploy obligations holds the run the same way. A final-delivery release refuses before execution
a same-project member whose selected flow it cannot close, so compose each
release on its members' own flow or reconcile the item's flow first. Automatic close-out ends an otherwise empty
holder session; the worker re-parks after an acceptance wake only while the
item remains at release wait, without rerunning merge for that acceptance.
Any prompt clears a park, so a held worker you message for
anything else is expected to re-park before it goes quiet again. The active
work claim retains the holder through idle and restart; the park records
the delivery wait for wake and recovery routing.

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

`yoke sessions terminate` is reserved for an unresponsive worker, a restaff
onto a different model (rule 9), or explicit cleanup. A worker whose process
exited between turns is not unresponsive until a message has failed to
resume it. In those cases, resolve the full session id from the launch that
staffed the item, then terminate it:

```text
yoke sessions terminate {WORKER_SESSION_ID} --reason "PREFIX-N unresponsive cleanup"
```

Logical termination cancels delivery and releases ownership immediately;
physical exit is a separate relay result. Each explicit request gets one
bounded TERM/KILL attempt (2 seconds grace, then up to 2 seconds exit
verification; Claude native job-stop command timeout 20 seconds). Missing
custody, signal denial or an unverified exit remains unresolved and retains
custody. Inspect the machine's custody/permissions and reap evidence, then
repeat the explicit termination command to retry a failed physical reap.
Pending attempts are not duplicated; verified success is a no-op on repeat.
Failed attempts remain in the existing reap record's evidence history.

Resolve `{WORKER_SESSION_ID}` from the launch that staffed the item
(`yoke session-control launch list --project {_project}` /
`yoke session-control launch get LAUNCH-ID`). No lingering. No re-tasking.

## 6. Every new item gets a fresh session

Never re-task an existing worker onto a different item. A new item is a
new `session_control.launch.create`.

## 7. Use the effective stage level at launch

**Judge the leg before every item launch:** well-specified mechanical
edits, small bug fixes, docs, routine cleanup → `--level JUNIOR`; trivial,
fully specified → `--level INTERN`; definition or implementation of real
design work → the stage level (omit `--level`); very complex → `--level
PRINCIPAL`. Depth: [`model-selection.md`](model-selection.md).

The stage level with its item override is what `workflows.item.get` returns as
`level`; an explicit `--level` overrides that one launch. The level's options
carry the model, effort, and context. What counts as a confirmed empty Cursor
pool, adopting a new model, and why a resume keeps its selection is
[`model-selection.md`](model-selection.md).
Set the item's level override when you staff it (same file). The mechanics
of an operator override are here.

An override names `--surface` with `--model`, `--reasoning-effort`, and
`--context-window` as needed; a knob it leaves unnamed takes the surface's
vendor default. It is recorded as `selection: override`. Preview shows the raw
request and its effective selection with each knob's source (`level SENIOR
option`, `explicit launch request`, `vendor default`); the launch retains both,
and the session shows the ask beside served facts. `--list-models` reports the
efforts and context windows the surface accepts and this machine's observed
models. An override preview ranks each machine by the meter the requested
model actually bills to, and names that pool's own quota under
`REQUESTED MODEL POOL`.
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

## 9. Restaff an in-flight item on a different model

When to move an item onto a stronger or cheaper model — the restaff ladder,
or a changed level override — is [`model-selection.md`](model-selection.md)'s
question. This is the how: one
item, one worker at a time, the same lane, no claim surgery. A parked
release-wait or landing holder is waiting on delivery, not failing; restaff
work that still has implementation or verification left to do.

1. **Read the checkpoint.** Every mandate tells the worker to append a
   Progress Log checkpoint before any stop, so a stopped worker has already
   left one. When the worker is live and its last checkpoint is behind its
   lane, ask for a fresh one and wait for it to land before terminating:

   ```text
   yoke items section get PREFIX-N --section 'Progress Log'
   printf '%s' "CHECKPOINT PREFIX-N: append a Progress Log checkpoint now, then stop; you are being restaffed" | yoke say --item PREFIX-N --stdin
   ```

   An unresponsive worker gets no wait: its successor reads the lane itself.

2. **Terminate the worker.** Termination releases its item claim and linked
   path claims, cancels its open messages, and reaps its native process. It
   does not touch the registered lane, the lane branch, or uncommitted work —
   those are what the successor resumes from. Resolve the session id from
   the launch that staffed the item:

   ```text
   yoke sessions terminate {WORKER_SESSION_ID} --reason "restaff PREFIX-N at {_level}: <why>"
   yoke claims work holder-get PREFIX-N
   ```

   A worker a wake is resuming refuses as `TERMINATION_RESUME_IN_FLIGHT`.
   A restaff is a deliberate kill, so re-run that termination with
   `--allow-resume-in-flight` once its checkpoint has landed.

   The holder read must show no live holder before you launch.

3. **Launch the successor** with the [launcher recipe](worker-launch.md), naming the new
   level. Give the idempotency key the predecessor's launch id, so a restaff
   onto a level the item already had is a new launch rather than a replay of
   the old one:

   ```text
   --idempotency-key "steer:{_project}:{ITEM}:restaff:{PREVIOUS_LAUNCH_ID}:{_level}"
   ```

   The server composes the mandate from the item's live stage, so the
   successor enters the skill bound there. Its mandate tells it to read the
   Progress Log and the lane before acting, keep the uncommitted work, and
   resume from the last checkpoint. A launch refused `item_has_live_worker`
   means the predecessor still holds the item; finish step 2 first.

4. **Confirm the handoff.** By its live `deadline_at`, the launch reads
   `state=succeeded` and `yoke claims work holder-get PREFIX-N` names the
   successor's session. The successor reports DONE for the item as its own
   leg; the predecessor sends nothing further.


Read [worker-launch.md](worker-launch.md) for launch, settlement, and mandate recipes.
