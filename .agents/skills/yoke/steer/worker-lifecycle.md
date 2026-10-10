# Steer — worker lifecycle and frontier discipline

Bind only under the paired seat/doc; workers never acquire/release either half.

## Quiet is not absent

Intentional external wait stamps parked with concrete reason. Reads, heartbeat,
ack, failed wake and tool calls do not unpark. Accepted UserPromptSubmit clears
prior park; later re-park advances turn_posture_at so a delayed earlier prompt
cannot clear it. Working-mode stamp resumes by choice. Verify mode/reason,
then resume only after blocker clears. Parked/in-flight/landing quiet is not
grounds to terminate or restaff. Active work claim protects its holder.

Headless process exits between turns normally: running→message it;
exited→message resumes transcript; resuming now→let start. Terminate only when
evidence says cannot resume, failed resume, or delivered resume got no answer.
TERMINATION_RESUME_IN_FLIGHT prevents killing an ongoing wake by accident.

## 1. Encode dependency edges before availability

Related batch files edges or explicit no-edges in the same action. Before staffing:

```text
yoke items dependency list PREFIX-N --json
```

Title-only related claimable batch without attestation refuses; don't launch
work frontier should not offer.

## 2. Keep the frontier maxed out

Staff every runnable unclaimed scoped item promptly, including work just filed
in this pass. Surfaces are not exclusive: as many concurrent sessions as the
work needs, not a one-session-per-surface cap. Capacity is level option/machine
capacity plus actual item set; balance never withholds a launch. There is no
per-surface session cap. Use [worker-launch](worker-launch.md), no second path.

## 3. Launch CLI surfaces only

claude-cli/codex-cli/cursor-cli default; desktop only explicit operator direction
or named exception. Preview every launch at the level judged under rule 7;
operator --surface names CLI, never the calling session's own.

```text
yoke session-control launch preview --project {_project} --level {_level} --json
```

Require launchable/rejection_codes/eligible_relays. Do not pick the machine or
the surface: level plane weighs authorized machine/options against their own
billing pools and spread/headroom. Read report levels dry-run, placement_reason
and level_placement. --machine only narrows; --surface is operator override.

| Refusal | Recovery |
|---|---|
| unsupported_surface | Preview supported CLI instead. |
| surface_disabled | Respect manual mark; use another option. |
| no_eligible_relay | Another eligible CLI/repair named relay. |
| machine_at_capacity | Actual live+assigned lane cap; free a lane, operator max_worker_lanes setting or --machine with room. No blind same-placement retry. |
| machine_access_denied | Read per-machine placement_reason; use authorized machine. |
| level_no_capacity | Named option/pool; deliberate permitted other level, reset wait or operator wall. |
| level_unknown | Read actual available levels. |

A refusal names the surface, not the item; continue other eligible work.

## 4. Route one item through its pinned workflow

```text
yoke workflows item get PREFIX-N --json
yoke charge schedule --project {_project} --item PREFIX-N --json
```

One worker owns exactly one item through returned entrypoint/remaining legs.
Never convert/re-file to fit Dash. Live stage's half-open binding owns next leg.
Worker cannot create deployment run; steering batches after merge boundary.

## 5. Workers self-end after their DONE report — only terminal

Merge/release wait is not done. Retain claim, park and remain owner through
delivery/postdeploy QA; don't ask release or terminate quiet holder. Native
wake stage/member acceptance routes to its owner; operator-wake desktop needs
operator prompt, never Yoke native resume. Owes-nothing member needs no prompt.
Selected/bound-source carrying flow alone owns actual shipped code's close-out.
Without run QA/approval own final production QA/post_deploy_no_obligation closes
member while siblings wait; shared run gates hold all final members through
all item/shared gates/run success. Unanswered/refused/interrupted settlement
remains executing and retains owed claims/lanes; re-drive same run. No fake
succeeded or same-project selected-flow mismatch. Automatic close-out ends an
otherwise empty holder. Re-park after acceptance only if item remains at wait,
without rerunning merge solely for acceptance; the worker stays the owner
through delivery; do not terminate it for being quiet.
The active work claim retains the holder through idle and restart; any prompt can clear prior park,
so it is expected to re-park before it goes quiet again.

Every worker sends the report deliberately, before releasing any claim it
still holds: DONE PREFIX-N summary through yoke say --steering, then self-END.
The PREFIX-N in the heading is the report identity: held/released work.
Ending a turn sends no Fleet message. Role reports survive seat turnover.
One report per work leg deduplicates reworded retry; resumed completion is its
new leg even with retained claim. Same episode/claim re-task still collapses
and reports substantive update instead. Never release a lane just to be heard.
No new item re-task or routine steering termination.

Termination is reserved for an unresponsive worker, restaff or explicit cleanup:

```text
yoke sessions terminate {WORKER_SESSION_ID} --reason "PREFIX-N unresponsive cleanup"
```

Resolve exact full session from recorded launch, no guessed UUID. Logical
termination cancels delivery/releases ownership; physical exit is separate
bounded relay TERM/KILL evidence (2s grace+2s verify; Claude job-stop 20s).
Missing custody/signal denial/unverified exit retains unresolved custody;
inspect permissions/reap history then explicit retry. Pending attempt never
duplicates; verified success repeats no-op. No fabricated native exit.

## 6. Every new item gets a fresh session

Never re-task a worker to another item: new session_control.launch.create.

## 7. Use the effective stage level at launch

Judge the leg before every item launch: mechanical edits/small bugs/docs/cleanup
→ `--level JUNIOR`; trivial fully specified → `--level INTERN`; real definition/
implementation → stage level (omit `--level`); very complex → PRINCIPAL.
Depth [model-selection.md](model-selection.md). Item-bound --level records an
every-stage item override, not only one launch. Running selection stays intact;
restaff to change it. Itemless/preview/exact override places one launch only.

Operator exact --surface/model/effort/context uses manifest accepted native
models/variants, recorded selection=override. Unnamed knobs take vendor default;
preview/receipt retains raw/effective selection and source; requested-model pool
is the meter billed. Read --list-models and manifest launch_model_selection.
Claude native encoding supports published 1M tier, Codex no explicit window,
Cursor exact advertised variant with effort once/native-labeled context only.
Never infer another model's window or append invented Grok brackets. Conflicts
refuse before spawn; model_combo_unsupported records bounded vendor detail:
choose supported combination/new launch, never silently drop flags/default.

## 8. Survey neighbour before ordered edit

Resolve holder and actual registered lane, never construct its pathname:

```text
yoke claims work holder-get --path SHARED_PATH
git -C ABSOLUTE_REGISTERED_NEIGHBOUR status --short
git -C ABSOLUTE_REGISTERED_NEIGHBOUR diff -- SHARED_PATH
```

One plain read-only Git invocation; current standing rules also allow named
read verbs. No redirects/chains/output/state moves or writes in another live
lane. Survey uncommitted intent, coordinate/dependency, then edit own lane.
Read lanes-and-claims before overlap remediation; survey is not write authority.

## 9. Restaff an in-flight item on a different model

One item/worker/same preserved lane, no claim surgery. Model-selection's ladder
owns when. Parked landing/delivery wait is not failure.
1. Read Progress Log/lane. Live worker behind checkpoint: request fresh one and
   wait before terminating. Unresponsive successor inspects lane itself.

```text
yoke items section get PREFIX-N --section 'Progress Log'
printf '%s' "CHECKPOINT PREFIX-N: append current Progress Log, then stop for restaff" | yoke say --item PREFIX-N --stdin
yoke sessions terminate {WORKER_SESSION_ID} --reason "restaff PREFIX-N at {_level}: reason"
yoke claims work holder-get PREFIX-N
```

2. Termination does not touch the registered lane, branch or uncommitted work.
   Verify no live holder. Resume-in-flight refuses; deliberate restaff may
   --allow-resume-in-flight only after checkpoint lands.
3. Preview/create successor with new --level and predecessor-specific key
   steer:project:item:restaff:{PREVIOUS_LAUNCH_ID}:level. Server composes current
   bound stage; successor reads checkpoint/lane, keeps work, resumes completed
   steps rather than replay. item_has_live_worker means finish termination first.
4. By live deadline_at require succeeded registration and holder-get names
   successor. New worker reports its own leg; predecessor sends no further mail.
