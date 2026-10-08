# Worker launch and settlement

## Launcher recipe

Read the live effective `level` with `yoke workflows item get {ITEM}` for
preview; item-bound create reads it again under the assignment lock.

A `level_change` handoff takes precedence over a release wait. Follow the
harness-neutral rule in `.yoke/docs/reference/session-level-routing.md` under
Stage-level handoff; workers may launch their own successor.

Preview is mandatory for every steering-staffed session, including itemless
ones. Do not create until preview returns `launchable=true` for the level.
Use `session_control.launch.create` for every launch. An
item-bound composed mandate requires `--item`; the server composes the
canonical single-item mandate from that ref and the charge-schedule route.
An explicitly itemless raw mandate requires `--raw-instructions --stdin` and
a nonempty body; it skips item lookup, terminal-item checks, and item-derived
naming. After a Yoke refusal, follow its named recovery through Yoke; never
substitute the Codex app `create_thread`, direct native CLI, or another
launch path. Every worker reports deliberately with
`yoke say --steering`. The mandate carries no session id: the report is
addressed to the steering ROLE. Do not hand-assemble an item-bound worker
body. Optional extras append after a composed mandate via `--stdin`.

```text
yoke session-control launch create \
  --project {_project} \
  --item {ITEM} \
  --idempotency-key "steer:{_project}:{ITEM}:{_level}" \
  --json
```

For one launch, add `--level {_level}` to override the effective stage level.
An exact operator selection adds `--surface {_surface}
--model {_model} --reasoning-effort {_effort} [--context-window {_context}]`
and names that selection in the idempotency key.

Itemless raw-instructions (explicit body, no `--item`):

```text
yoke session-control launch create \
  --project {_project} \
  --level {_level} \
  --raw-instructions --stdin \
  --idempotency-key "steer:{_project}:raw:{_level}:{_purpose}" \
  --json <<'EOF'
<complete itemless mandate>
EOF
```

Managed `claude-*` launches are local-only per launch: Yoke disables Claude
Remote Control without changing the operator's normal Claude settings. A
composed launch's display name is derived from `{ITEM}` plus its
authoritative backlog title; the instruction body never becomes a title or
command-line argument. Itemless launches omit that name.

Retain the returned `launch_id`. The launch's `deadline_at` window starts when
its machine's relay picks it up, not at create: a launch still `assigned` is
queued behind that machine's earlier native creates, and pickup moves
`deadline_at` to the pickup time plus the full window. A queued launch closes
early only when its relay disconnects past the create-time deadline or when it
outlasts the queue bound (`LAUNCH_QUEUE_WAIT_SECONDS`, one hour). Read the live `deadline_at` from `launch get`; by that
deadline, require `state=succeeded` and a non-empty `registered_session_id`:

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

Re-running that one command is the whole close-out, and it stays the whole
close-out however long the wait ran. The merge-group proof is recorded when
the train lands and read back at the wake, and delivery is answered by
whether a succeeded run of the item's selected flow contains its merge rather
than by whether that run happened to enrol it. Neither decays. So a worker
that reaches the wake owes steering a report only when the close-out refuses,
and a refusal that says a retry cannot help is a blocker to report rather
than a loop to run. Workers must not reach for `done-transition
--skip-deploy` to get past one: it records delivery as out-of-band, the done
engine refuses it when the selected flow already delivered the item, and
using it on a selected-flow release writes a false record of how that release
happened.

### Vet each landing before it enters a release

A worker merges as soon as its gate is green, and that is the design. Do not
hold merges, and do not make your review a precondition of landing: a seat
that gates landing becomes the fleet's bottleneck, and the failure it
prevents is cheaper to correct afterwards than to queue for.

What you owe instead is vetting, as soon as you can and **always before the
item is admitted to a deployment run**. Read the exact diff and the evidence
covering it — `yoke items detail get PREFIX-N --json` for the merge identity
and QA rows, `git -C {CHECKOUT} diff {BASE_SHA}...{LANDED_SHA}` for the code
itself. A DONE report is a prompt to vet, never the vetting.

When vetting finds a problem, the item goes back to its owner to correct:
fix, re-verify, re-land, re-enter release. The registered rework transition
is a backward move, which the declared-transition gate leaves to rework
rather than refusing.

`lifecycle.transition` requires the calling session to hold the item's
work claim, so the steering seat does not make this move on a worker-held
item — it would be refused `claim_required`, and taking the claim to force
it would evict the worker mid-lane. Steering names the correction to the
holder; the holder transitions its own item:

```text
yoke say --item PREFIX-N --stdin <<'EOF'
REWORK PREFIX-N: <what to correct, and the evidence it fails>
EOF
```

```text
yoke lifecycle transition PREFIX-N --to implementing --reason "steering rework: <what to correct>"
```

The first command is steering's; the second is the holder's. When the item
has no live holder, steering acquires the claim itself and then transitions
— `yoke claims work holder-get PREFIX-N` answers which case this is.

**An item with an unresolved vetting problem is not admitted to a
release** — hold it out of the batch rather than shipping it and
correcting after.

The `merge_candidate_review` posture still exists for an item a human owner
explicitly wants held before it lands; it is not the default, and steering
does not select it.

The same mandate names the opposite failure, because a launched turn is the
whole life of every command it starts. When the harness moves a long command
to a background task, the child keeps running; a worker that read that
hand-back as completion ended its turn and killed the merge it was holding,
twice in one night, reporting success with no verdict recorded. The mandate
therefore tells the worker to continue the handed-back call until it exits,
and to stop early only for a command-handed wait or the taught local-check interrupt.

```text
{ROUTED_ENTRYPOINT}

Single-item mandate (steering): acquire the PREFIX-N work claim as your FIRST action — `yoke claims work acquire --item PREFIX-N --reason "<why you are claiming it>"` — then execute only PREFIX-N through {ROUTED_LEGS}. Do NOT create or dispatch any deployment run — the orchestrator batches deploys. Message the orchestrator ONLY for substantive updates — a red gate and what failed, a blocker, a conflict with this instruction, a defect outside your scope, a decision you need. NEVER send progress: no percentages, elapsed-time polls, watcher heartbeats, or "still green" notes; relay those in your own output instead. For a substantive peer request or reply, address the intended worker/session AND copy relevant steering using union recipient flags (`--item PREFIX-N --steering`, or an exact listed `--session SESSION-ID --steering`; use explicit `--steering-scope '{"project_id": N}'` when you hold no applicable item). Reply to the original requesting session for acceptance, refusal, scope conflict, blocker, or decision; never send a rejection only to steering. Acknowledgement records receipt, not acceptance or implementation. When those legs are complete, message the orchestrator (`printf %s "DONE PREFIX-N <one-line summary>" | yoke say --stdin --steering`) and END your session — do not pick up further work, do not chain into other items. Send that report before releasing any claim you still hold; after close-out already released it, `--steering` resolves from the item you last held in this session. The PREFIX-N in the DONE heading is the report identity and must name work this session holds or released. If your claim is swept mid-work, reacquire and continue.

Keep the item resumable by another worker. Steering may restaff it onto a different model at any point by terminating this session, which releases your claim and leaves the lane, its branch, and any uncommitted work in place for the successor. So before any stop short of done — a park, a blocker or decision report, a landing or release wait, or the end of a turn — append a Progress Log checkpoint naming the live stage, what is committed, what is still uncommitted in the lane, and the next concrete step: `yoke items progress-log append PREFIX-N --headline "<checkpoint>" --stdin`. When the item you claim is already past its first stage, you are that successor: before acting, read `yoke items section get PREFIX-N --section 'Progress Log'` and the lane's `git status` and `git log`, keep the uncommitted work you find, and resume at the live stage from the last checkpoint rather than repeating transitions or steps it records as done.

An item whose posture selects merge_candidate_review may not land until a person has cleared the exact commit. `yoke merge item` refuses an uncleared candidate by name, before it arms, enqueues, or merges anything, and names the open decision request an authorized reviewer answers. You cannot answer it yourself: the session holding the item's work claim is refused by name, whatever actor it carries, and so is clearing the posture key. That refusal is a blocker, not a retry: report it with the request id and stop. Any commit you make after a clearance needs its own review, so commit everything first, then merge.

A merge that lands your item at its pinned release wait is a completed merge that is NOT a finished item: the delivery still has to run and its post-deploy validation still has to be walked before the item reaches done. That close-out therefore keeps your work claim and parks your session with the wait named, and you keep both. Do NOT release the claim and do NOT end your session there — report what landed in your own output, say you are waiting on delivery, and stop deliberately. The close-out block names what your item owes delivery and whether your session can be woken; report what it says. When it owes an item-scoped QA stage, a deployment wake re-enters you, on a natively wakeable surface, when that stage needs you or your own item-scoped QA is accepted. A surface whose wake authority is operator (a desktop app) is never woken by Yoke: say so, because the operator or a steering seat must re-enter you. When it owes nothing, delivery closes the item itself and nothing will ask you for anything. A final member whose selected flow has no run QA or run approval closes when its own final production QA is accepted or explicitly discharged by `post_deploy_no_obligation`, even while sibling QA holds the run open. A flow with run QA or run approval holds every member until all item gates and shared gates pass and the run succeeds. These close-outs need no extra wake and end an otherwise empty holder session. A stage that wants your evidence is run by naming that stage AND your item, because a stage credits only requirements bound to its own name: `yoke watch qa-plan -- --deployment-run-id RUN --stage STAGE --member <ITEM> --project P` (that wrapper, not `yoke watch qa-case`, which wraps the narrower requirement-id form). Add `--plan PLAN` only when the wake says the stage names no cases: a stage that already names its own refuses --plan except for a correction-only plan whose every case names its failed admitted requirement with --replaces CASE_KEY=FAILED_REQUIREMENT_ID. The wake prints the exact recipe for its own stage. The run-wide form and `yoke qa case run` do not credit it. After the item-scoped stage is accepted, check whether the item reached done; otherwise re-park while its completion flow finishes. Do not re-run merge solely for that acceptance. A delivery wake is reserved for a cleared member the automatic close-out could not finish, and names the required recovery. Only once the item reaches done do you send the DONE report and end. Any prompt that wakes you CLEARS that park, including one that turns out not to finish the item, so whenever you go quiet still short of done — a wake you handled, a close-out that refused, a message about something else — re-park before stopping: `yoke sessions touch --mode parked --reason "awaiting <ITEM> delivery"`. The active work claim protects the session; parking records its delivery wait for wake and recovery routing.

Steering does not gate your landing — it vets your work after it lands and before the item is admitted to a release. If that vetting finds a problem, steering tells you what to correct and asks you to move the item back to implementing — that transition is yours, because `lifecycle.transition` requires the calling session to hold the item's work claim and you are the holder. That is a rework leg on the SAME item, not a new one and not a refusal to argue with: correct it, re-verify, re-land through the same merge command, and re-enter the release wait. Previous evidence covered the revision it was taken on and does not carry over to the corrected one. Escalate instead only when you cannot do the correction, naming what blocks you.

You are a headless command that cannot be prompted again, so a merge-queue landing is not yours to wait out: it outlasts your turn, and a wait that dies with the turn leaves the branch landed and the item open. Your merge arms the landing and returns landing_pending=true with the pull request named, whether or not you passed --wait. That is the handoff, not a failure. Report the pull request, stop deliberately, and say you are waiting on landing. The control-plane landing notice wakes you: re-run the same `yoke merge item` command then and it completes close-out. A stopped landing arrives the same way and names its recovery (usually rebase, re-run the verification gate, re-run the command); a stale server landing record names its last refresh and repair step. Never replace either with local GitHub polling, and never report a landing you did not read. A separate check uses `yoke github merge-queue readiness PREFIX-N --json`: the named queue-entry state decides whether null arming was consumed or cleared.

A tool call that outlives its yield is still running. When your harness moves a long command to a background task or hands back a continuation handle, that is the harness handing the call back, not an interruption: the child and whatever it is waiting on are still alive. Continue that same call through your harness's continuation surface until it exits and you have read its outcome — reading the background task's output continues the call, and only ending the turn kills the watcher and the child it was holding, which lands as a killed capture with no recorded verdict. Never start a second invocation beside a live one; re-run only once the first process is verifiably gone. Stop before a command finishes only where the command itself handed the wait off — a merge that returned landing_pending has its landing notice — or, as the explicitly taught exception, when a *local* test check on a project with declared CI has already exceeded about one minute: interrupt that test process cleanly, keep the capture as incomplete, commit, and continue the selection on that project's CI. Do not interrupt a CI-routed watcher, a machine-specific diagnostic, or a local run on a project without CI, and do not background the slow local selection to keep waiting.

Ending a turn sends no Fleet message. Send the DONE report deliberately, as `printf %s "DONE PREFIX-N <one-line summary>" | yoke say --stdin --steering` — the body rides stdin, so the command refuses without `--stdin`. Lead with the `DONE PREFIX-N` heading naming work this session holds or released, then what landed, what is blocked, and what you need — before ending the session.
```

The server parameterizes that shape from the item's pinned skill binding.
`charge.schedule` returns its `next_step` and the rendered `entrypoint`; the
launch mandate uses the same entrypoint mapping. Read
`yoke workflows version get <workflow> <version> --json` for the ordered stages,
transitions, and half-open skill intervals instead of copying a workflow chain.

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
the pinned release wait. The work claim protects the session without a
retention deadline; the park identifies the delivery wait for wake routing.

That write persists until the worker stamps a working mode
(`yoke sessions touch --mode dash`) once the wait clears. Reporting the
wait, or knowing its reason, is not the state change and does not unpark
— only the mode stamp does, and control-plane reads never unpark either.

Parking also shields what the worker holds. Its work claim stops reading as
stale on inactivity alone, so the item keeps a live holder on the board
rather than appearing available to staff, and neither the offer sweep nor a
competing acquisition can reclaim it. A QA plan execution whose owner is
parked is not reaped as stale either, so a walker told to hold keeps its
mission rather than losing it to the sweep. That shield lasts as long as the session
does: if the park outlives the session — a sleep, a reload, an end — the
sweep settles the execution and stamps its capture with an error verdict.
The Test Machine still holds the walk's state, and the walker re-enters with
the `yoke qa plan run ... --continue-mission` command its next
`yoke qa mission host-command` refusal names. Tell a held walker to continue
rather than to re-run the plan; an ordinary run resets the host.

Use this recipe for every launch, whether an item just became runnable,
the fleet report named it as available, or the steering request is itemless.
Item-bound frontier staffing remains the default. Both shapes use the same
Yoke launch path on a CLI surface; the server composes item-bound mandates.
There is no second staffing path.

When same-surface worker failures carry a vendor-side signature, disable
that surface with `yoke session-control surface-policy disable` and staff
onto the other harnesses. Do not mark unclassified failures. Re-enable
only after one successful canary launch. See the Surface disable marks
section in `SKILL.md`.
