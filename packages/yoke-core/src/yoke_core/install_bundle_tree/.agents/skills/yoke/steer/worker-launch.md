# Worker launch and settlement

A level_change handoff precedes release wait: use Stage-level handoff in
.yoke/docs/reference/session-level-routing.md; workers may launch successor.
Read effective level/pin and charge.schedule's rendered `entrypoint`; launch
mandate uses the same entrypoint mapping. One assigned item/live bound skills,
never copied workflow chain. Read yoke workflows version get <workflow> <version> --json.

Every launched worker, whatever its origin, is a headless command: a launched
turn is the whole life of every command it starts. Never read that hand-back
as completion while a yielded handle is still running. Continue that handle;
stop early only for a command-handed wait or the taught local-check interrupt.
Ending a headless turn without a verified wake leaves it waiting for a
re-entry nobody could make; the control-plane landing notice is what closes
that gap for the declared stopped-session path. Follow the selected wait mode.

## Preview, create, confirm

Preview every steering-staffed item or itemless session. Do not create until
preview returns launchable=true. Only session_control.launch.create: no native
CLI/create_thread/alternate path after refusal. There is no second staffing
path. Itembound --item means the
server composes it; Do not hand-assemble a worker body. --stdin optionally
appends extras. Explicit itemless --raw-instructions --stdin requires nonempty
body, skips item lookup/terminal checks/title. Both use the same CLI launch path.

Judge the leg before every item launch: mechanical/small bug/docs/cleanup →
`--level JUNIOR`; trivial specified → `--level INTERN`; real definition/design/
implementation → stage level (omit `--level`); very complex → PRINCIPAL.
Read [model-selection.md](model-selection.md). Judged level goes to preview and
create; itembound records every-stage override/Item level receipt, not a
stage-edge handback. Exact operator --surface/model/effort/context excludes
level and names selection in key. No live-session model editing.

```text
yoke session-control launch preview --project {_project} --level {_level} --json
yoke session-control launch create --project {_project} --item {ITEM} --idempotency-key "steer:{_project}:{ITEM}:{_level}" --json
yoke session-control launch create --project {_project} --level {_level} --raw-instructions --stdin --idempotency-key "steer:{_project}:raw:{_level}:{_purpose}" --json < MANDATE_FILE
yoke session-control launch get {LAUNCH_ID} --json
```

Managed Claude launches disable Remote Control locally for that launch only.
Composed display name comes from ref+authoritative title, never body/CLI
argument; itemless has no derived name. Retain launch_id. deadline_at starts
at relay pickup; assigned waits behind native-create queue. Relay disconnect
or declared queue bound can end it early. Read actual live deadline and require
succeeded/nonempty registered_session_id, then verify holder.
spawn_started/spawn_alive owns first process: wait through deadline, reconcile
refuses native_process_alive, retry reattaches without duplication. After
containment/no live phase, read named failure then reconcile/retry:

```text
yoke session-control launch reconcile {LAUNCH_ID} --json
yoke session-control launch retry {LAUNCH_ID} --json
```

Repeated relay_lease_expired on one surface: deliberate other CLI placement,
immediate field-note with launch ids/codes. Replay whose session ended refuses
launch_replay_finished; new worker requires fresh intentional key.

## Substantive reporting and peer requests

Every worker gets the `yoke say --steering` DONE step. ROLE resolves held/last-held
item to current seat, or awaiting_seat scope parked for successor; receipt
names delivered seat or parked scope. No session UUID in mandate; never pad,
complete, or expand one by hand. Launch origin does not change that boundary.
Ending a turn sends no Fleet message. Send red gate/block/conflict/out-of-scope
defect/terminal/decision only, not progress/heartbeat/elapsed/still-green mail.

Substantive peer request must reach worker AND steering: yoke say --item
PREFIX-N --steering --stdin. Recipient replies to EXACT requesting session
with --steering copied; claimless uses --steering-scope '{"project_id": N}'.
Never send refusal only to steering or reconstruct UUID. Ack is receipt only;
acceptance/refusal is substantive reply. Show progress in own visible output.

## Vetting and holder-owned rework

Steering vets exact landed diff/QA before run admission, not default landing
hold. Unresolved problem stays out of release. Candidate-review posture is
explicit human choice; steering does not select it. Live holder transitions
same item back to implementing, fixes/re-verifies/re-lands/re-enters release;
old candidate proof cannot credit corrected tree. Steering cannot seize claim
to perform that transition. No live holder: acquire then transition under
registered pin/rework gate. Resolve which through holder-get:

```text
yoke claims work holder-get PREFIX-N
yoke say --item PREFIX-N --stdin <<'EOF'
REWORK PREFIX-N: correction and failed evidence
EOF
yoke lifecycle transition PREFIX-N --to implementing --reason "steering rework: correction"
```

First message is steering's; transition is holder's. Escalate only actual
inability with named blocker. Delivery proof/merge-group receipts do not decay
with wait age. Own selected-flow succeeded containment, not enrollment alone,
owns close-out. Rerun same merge on landing wake; nonretryable refusal reports
blocker, never looping or done-transition --skip-deploy false out-of-band record.

### Single-item mandate (steering)

Claim first; execute only assigned live bound legs and checkpoint reentry.
Do NOT create or dispatch any deployment run. Substantive role reports only;
DONE/END only terminal. One worker retains release wait; steerer batches.
The following expanded phase obligations remain exact for steering review;
workers read their bound phase/rules before acting rather than receiving this
whole block in every compact launch.

```text

Keep the item resumable by another worker. Steering may restaff it onto a different model at any point by terminating this session, which releases your claim and leaves the lane, its branch, and any uncommitted work in place for the successor. So before any stop short of done — a park, a blocker or decision report, a landing or release wait, or the end of a turn — append a Progress Log checkpoint naming the live stage, what is committed, what is still uncommitted in the lane, and the next concrete step: `yoke items progress-log append PREFIX-N --headline "<checkpoint>" --stdin`. When the item you claim is already past its first stage, you are that successor: before acting, read `yoke items section get PREFIX-N --section 'Progress Log'` and the lane's `git status` and `git log`, keep the uncommitted work you find, and resume at the live stage from the last checkpoint rather than repeating transitions or steps it records as done.

An item whose posture selects merge_candidate_review may not land until a person has cleared the exact commit. `yoke merge item` refuses an uncleared candidate by name, before it arms, enqueues, or merges anything, and names the open decision request an authorized reviewer answers. You cannot answer it yourself: the session holding the item's work claim is refused by name, whatever actor it carries, and so is clearing the posture key. That refusal is a blocker, not a retry: report it with the request id and stop. Any commit you make after a clearance needs its own review, so commit everything first, then merge.

A merge that lands your item at its pinned release wait is a completed merge that is NOT a finished item: the delivery still has to run and its post-deploy validation still has to be walked before the item reaches done. That close-out therefore keeps your work claim and parks your session with the wait named, and you keep both. Do NOT release the claim and do NOT end your session there — report what landed in your own output, say you are waiting on delivery, and stop deliberately. The close-out block names what your item owes delivery and whether your session can be woken; report what it says. When it owes an item-scoped QA stage, a deployment wake re-enters you, on a natively wakeable surface, when that stage needs you or your own item-scoped QA is accepted. A surface whose wake authority is operator (a desktop app) is never woken by Yoke: say so, because the operator or a steering seat must re-enter you. When it owes nothing, delivery closes the item itself and nothing will ask you for anything. A final member whose selected flow has no run QA or run approval closes when its own final production QA is accepted or explicitly discharged by `post_deploy_no_obligation`, even while sibling QA holds the run open. A flow with run QA or run approval holds every member until all item gates and shared gates pass and the run succeeds. These close-outs need no extra wake and end an otherwise empty holder session. A stage that wants your evidence is run by naming that stage AND your item, because a stage credits only requirements bound to its own name: `yoke watch qa-plan -- --deployment-run-id RUN --stage STAGE --member <ITEM> --project P` (that wrapper, not `yoke watch qa-case`, which wraps the narrower requirement-id form). Add `--plan PLAN` only when the wake says the stage names no cases: a stage that already names its own refuses --plan except for a correction-only plan whose every case names its failed admitted requirement with --replaces CASE_KEY=FAILED_REQUIREMENT_ID. The wake prints the exact recipe for its own stage. The run-wide form and `yoke qa case run` do not credit it. After the item-scoped stage is accepted, check whether the item reached done; otherwise re-park while its completion flow finishes. Do not re-run merge solely for that acceptance. A delivery wake is reserved for a cleared member the automatic close-out could not finish, and names the required recovery. Only once the item reaches done do you send the DONE report and end. Any prompt that wakes you CLEARS that park, including one that turns out not to finish the item, so whenever you go quiet still short of done — a wake you handled, a close-out that refused, a message about something else — re-park before stopping: `yoke sessions touch --mode parked --reason "awaiting <ITEM> delivery"`. The active work claim protects the session; parking records its delivery wait for wake and recovery routing.

Steering does not gate your landing — it vets your work after it lands and before the item is admitted to a release. If that vetting finds a problem, steering tells you what to correct and asks you to move the item back to implementing — that transition is yours, because `lifecycle.transition` requires the calling session to hold the item's work claim and you are the holder. That is a rework leg on the SAME item, not a new one and not a refusal to argue with: correct it, re-verify, re-land through the same merge command, and re-enter the release wait. Previous evidence covered the revision it was taken on and does not carry over to the corrected one. Escalate instead only when you cannot do the correction, naming what blocks you.

You are a headless command that cannot be prompted again, so a merge-queue landing is not yours to wait out: it outlasts your turn, and a wait that dies with the turn leaves the branch landed and the item open. Your merge arms the landing and returns landing_pending=true with the pull request named, whether or not you passed --wait. That is the handoff, not a failure. Report the pull request, stop deliberately, and say you are waiting on landing. The control-plane landing notice wakes you: re-run the same `yoke merge item` command then and it completes close-out. A stopped landing arrives the same way and names its recovery (usually rebase, re-run the verification gate, re-run the command); a stale server landing record names its last refresh and repair step. Never replace either with local GitHub polling, and never report a landing you did not read. A separate check uses `yoke github merge-queue readiness PREFIX-N --json`: the named queue-entry state decides whether null arming was consumed or cleared.

A tool call that outlives its yield is still running. When your harness moves a long command to a background task or hands back a continuation handle, that is the harness handing the call back, not an interruption: the child and whatever it is waiting on are still alive. Continue that same call through your harness's continuation surface until it exits and you have read its outcome — reading the background task's output continues the call, and only ending the turn kills the watcher and the child it was holding, which lands as a killed capture with no recorded verdict. Never start a second invocation beside a live one; re-run only once the first process is verifiably gone. Stop before a command finishes only where the command itself handed the wait off — a merge that returned landing_pending has its landing notice — or, as the explicitly taught exception, when a *local* test check on a project with declared CI has already exceeded about one minute: interrupt that test process cleanly, keep the capture as incomplete, commit, and continue the selection on that project's CI. Do not interrupt a CI-routed watcher, a machine-specific diagnostic, or a local run on a project without CI, and do not background the slow local selection to keep waiting.

Ending a turn sends no Fleet message. Send the DONE report deliberately, as `printf %s "DONE PREFIX-N <one-line summary>" | yoke say --stdin --steering` — the body rides stdin, so the command refuses without `--stdin`. Lead with the `DONE PREFIX-N` heading naming work this session holds or released, then what landed, what is blocked, and what you need — before ending the session.
```

An accepted turn prompt can clear prior park; mere reads/acks/tool calls cannot.
Intentional upstream/sign-in/approval/operator wait records concrete parked
reason; working-mode stamp resumes when actually proceeding. Release close-out
stamps park itself; active work claim protects holder across idle/restart.
Live parked QA owner is protected too. Logical ended execution settles/error
capture under recorded authority; Test Machine host state remains. Re-enter
the --continue-mission command named by qa mission host-command refusal,
never ordinary plan rerun resetting the host.

One registered staffing path for every runnable/report/itemless launch.
Classified vendor signature uses manual surface-policy disable/rebalance;
unclassified escalates. Successful canary alone re-enables per close-out.
