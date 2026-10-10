# Steering fleet report

The server composes reports for the calling session's held steering scopes;
reporting never staffs work. `yoke steering report get` combines them;
`--project P` filters a scope and `--full` retrieves complete detail.
Headings use project slug or `<project> · <document>`.

## Scope and available work

Document seats follow item_strategy_docs membership, including execution in
other projects. Available work, holders, landing/dead-wait rows and mail to
those holders follow that membership. Project seats cover unlinked items and
CURRENT-PLAN members. Other-document work with no live seat appears as
unattended linked work with owning project/acquire command. Machines, delivery
and unbound launches remain project-wide/shared facts.

Available work leads: scheduler-runnable unheld rows, ranked, `new` or `stopped`
by prior claim release, `!` after staffing threshold. Quiet holders still own
their items: idle never makes work available. Release/completion/cancellation/
authorized termination changes custody; freeze/block are deliberate holds,
cancel ends work. No age-inferred holds or staffing.

## Holder and landing detectors

| Section | Evidence and response |
|---|---|
| idle holders | No tool call beyond threshold, excluding proven open queue/armed landing with no failed required checks; merged/dead/unreadable/failed landing returns to ordinary idle rules. Light roster's awaiting-landing fact drives probe; missing fact retains alarm. Full landing details load only when report is due. |
| in flight | Quiet running holder inside a budgeted watcher/landing call. Unknown/waiting posture, observed native exit (even clean), denied/closed call, a call overtaken by later activity or one older than 45 minutes cannot excuse silence. Terminal vendor-turn observation survives same-turn tool settlement. |
| landing readbacks | Current nonmutating `yoke github merge-queue readiness PREFIX-N --json`: one status/checks GraphQL read per PR and shared repository/base queue read per request; no cache across reports. |

Landing rows show queue-entry AWAITING_CHECKS/UNMERGEABLE/MERGEABLE/absent/unreadable
and arming. GitHub consumes autoMergeRequest when an entry forms: null arming
with entry means consumed/in-flight; absent entry plus null arming means cleared
and `!`. Entry decides liveness, not null arming alone.

Parked holders are expected waits unless native death is proven. A stopped turn
with unfinished call is immediately idle (declared park remains a wait).
Process rows distinguish:

- running: message it;
- exited on a surface declaring message_stopped: message to resume transcript;
- resuming: wake_relay started at/after exit and still open, or resumed without
  another exit within resume-custody quiet window; no process-gone alarm;
- gone on a surface unable to resume by message: deliberately terminate if dead;
- contained by sweep: only with recorded containment reason, never inferred
  from unexplained exit. Exhausted/rejected/unavailable-model cases go to stranded.

`yoke sessions terminate` refuses TERMINATION_RESUME_IN_FLIGHT unless
--allow-resume-in-flight. sessions.list native_process exposes resuming with
resume_started_at, or gone with resumable_from_transcript. Ended/terminated
sessions are excluded from holder alarms, not repeatedly called idle.

## Undelivered messages

Rows group recipient + delivery state, count, up to three ids and oldest age.
Membership uses the delivery plane's deliverable-receipt predicate, not stored
pending alone: injected/acknowledged/expired/cancelled receipts are finished,
including between expiry and sweep. Sender is not a filter.

Send once to a parked wake-capable worker; relay resumes it and hook reads mail.
Relay leases one job at a time: termination/evidence, eligible wakes, then
launches. A wake refusal keeps its error code/message/recovery even with empty
result; human stderr and JSON envelope preserve it. Read it before retry.

Eight states remain distinct:

| State | Meaning and action/fingerprint |
|---|---|
| never attempted | Plane owes an attempt after acknowledgement grace measured from recipient's last tool call plus one poll. Prior silence counts. Actionable. |
| last attempt failed | Immediate exact diagnostic (adapter/eligibility/hook reason, or unreported when absent), with ×N repeat count. Two failed attempts remain a failure even during an open call. Actionable. |
| attempt in flight | Accepted resume not settled. Waiting; not actionable or fingerprinted. |
| queued for next hook | Hook/window means no attempt owed yet. Waiting; not actionable or fingerprinted. |
| recipient turn in flight | Live open call since its actual time; message lands at return hook even past stale/idle threshold. Waiting; not actionable or fingerprinted. |
| wake held for native turn | Machine verified pid/start identity still running between calls. Gives attempt back and keeps envelope pending. Fingerprinted, not actionable; no automatic second turn. |
| recipient ended without remaining route | No parked/waiting declaration; sender/seat cancels envelope and re-sends content to intended successor. No automatic successor or acknowledgement. |
| recipient terminated | Deliberate end has no route; same cancel/re-send recovery. |

Ended parked/waiting recipients retain their supported transcript routes;
ended_at alone is not proof mail is undeliverable. Terminated always has no
route. For gone recipients use `yoke messages cancel MESSAGE-ID`; cancel does
not deliver content.

Queued explicit wake with no attempt names `yoke session-control session wake
SESSION-ID` only after every receipt reaches its own acknowledgement grace.
Before then it reports releasable-at timestamp and no command; a younger queued
receipt still causes wake_in_flight. A single failed attempt overtaken by a
live call may defer; repeated failures retain precedence.

Native-held rows name the native and, when measurable, its no-output age from
the capture's own clock, not periodically refreshed file mtime. Missing old
clock means unknown, never recent output. Parked declares wait, not native
exit. Codex active-writer/background_session_in_use is native_turn_running
deferral, not a steering failure notice. Observed exit reopens a busy receipt
even at retry limit; silence alone cannot reopen exhausted unparked receipt.
Verified exit retires orphan open calls. Explicit operator wake retains its
intentional semantics; automatic wakes never start a second live turn.

wake_escalation qualifies actionable rows: starved_hook_route,
parked_without_idle_wake, native_process_gone. Park/no-idle-wake and stored
native exit escalate immediately, not after another grace; later activity
retires observations. Clean exited parked/landing workers resume stored native
identity on their next message while their holder wait remains expected.
Readable machine observation, not heartbeat age, proves exit.

Refused/exhausted wakes send one bounded role-addressed notice per failure to
covering steering, with original message/target/diagnostic. outcome_unknown
notice waits for next completed tool call when no live call remains and is
suppressed if acknowledged. Notices never recurse into failure notices.
Late native recovery applies only to manifest message_stopped surfaces.
Desktop/IDE operator wake authority is never automatically resumed: next user
input injects mail, and beyond grace an actor-addressed Inbox notice names that
need. Do not label progressing/failed deliveries as operator waiting.

Every row names machine evidence: `yoke session-control evidence get --session
SESSION-ID`, plus --evidence-id when diagnostic reference exists; see
[machine-local-evidence.md](machine-local-evidence.md).

## Stopped sessions and launches

Vendor-stopped rows use stored native turn record on readable-manifest surfaces,
persisting provider words/classification/time and HarnessSessionTurnEndObserved
telemetry. Stored recovery survives telemetry retention. Turn-end-hook surfaces
already settled and declare that reason. Recoverable capacity/client-build
refusals retry with widening bounded backoff; show next attempt/time. Exhausted
quota/rejected credentials or exhausted retry budget need seat action; only
those rows are actionable.

Stranded sessions cannot resume: exhausted published model pool, rejected
credentials or removed model. Show count/items/relaunch on available headroom,
never automatic model substitution/wake. Preferred-default drift is not a wall;
still-registering sessions within deadline are excluded. Unknown/unreadable
meter is not exhaustion; only that model's own zero pool is. Wake refuses
meter_exhausted with remaining/reset; recurring resumed-died may project
blocked-meter-exhausted.

Unregistered launches report immediately for failed correlation or exact
active harness session lacking binding; otherwise after deadline_at. Deadline
starts at pickup, not queued time. State that mandate was not delivered;
reconcile before retry. Live native: bind it; exited native: reconcile/retry,
with exit/last line and session evidence read. Exclude unrelated closed history.
Abandoned launch: delivered mandate but no claim/outbound message/completed
call, native gone; show session/closed age/exit/last line, restaff unstarted work.
Rows expire after six hours.

## Landed work and dead waits

Landed-without-close-out uses item merged_at or merge_queue_landed_at plus
nonterminal state; control-plane observer records landing even if waiter died.
A parked live release holder with active completion flow reports compact
awaiting-deployment-run or delivering-in-RUN; silence is expected. Missing/gone
holders, aged working holder + landing, unavailable flow, remerged/unreadable
custody or actionable run keeps full detail. Section owns these rows; never
duplicates idle/live holders or members already shown in deployment runs.

Close-out requires holder claim: never propose seat recovery against a live
holder. Orphan rows alone name pinned workflow recovery including --result/
--verification when close_out_evidence_gate requires them. delivery_landing_custody
agrees with enrollment: delivering-in-run, no-release-holds-it (expected
enrollment for valid parked wait), or merged-again-since-run. Losing custody
changes identity/wakes; moving between releases does not. Merge time starts
landing age; a queue waiter becomes quiet only after full landing idle threshold,
while rows retain actual landing age/tool silence.

Dead waits scan recent outbound conversation for real interrogative/explicit
reply requests, not confirmations or latest message alone. Reply already received
wins; ended answerer or terminal answerer's item proves no reply possible.
Live answerer is unresolved; no question means no row. Steering-role question
survives seat succession and belongs to awaiting-seat count, not dead waits.

## Deployment runs

All nonterminal project runs show run/status/flow/current stage/age, outstanding
blocking obligations/total and determinate reds. Tables and bounded QA/current
receipts/latest reds/resolved decisions load once per request, not per-run
query cascades. Healthy running rows have no actionable mark/recovery.

Red rows name requirement/member and containment against that member's own
project pin: release_lineage for run project, bound start commit for others.
Never compare across projects. Definite remediation outside frozen lineage
cannot pass here: independent item QA names remove-item with reason, or shared
gate needs a superseding run above remediation. Failed independent QA/settlement
releases definitely-outside members; unknown containment holds. Unreadable
provider/source evidence is unproven with reason/recovery, not a report failure
or invented impossibility. No recorded merge makes no containment claim.
Report never terminalizes, waives or supersedes.

At scoped QA stage, outstanding is native qa_stage_outstanding. Each waiting
member reports blocker count and newest owner notice: wake-pending, woken-time
(failure-handoff labelled) with furthest receipt acknowledgement/delivery, or
not-woken reason (expired/failed/cancelled, no holder/seat, gone/stale driver).
One notice + at most two addressability reads per run; detailed requirement
reasons stay on `yoke deployment-runs stages RUN`. Wakes precede empty-member
close-out; missing wake is a defect, not instruction to message owners manually.

Waiting-only-to-be-driven means created with no live driver. created + live
driver may be silent phase; executing does not call for duplicate drive even
with no obligations. Other stages use native unresolved_blocking_qa and
blocking_obligation_total. Only red or created/no-outstanding/no-driver shapes
require decision; re-drive recovers a proven dead driver. No timeout/auto-cancel.
Current-stage resolved approval/rejection shows request/time while run remains
there; decision_requests.consumed_at is item-lifecycle consumption and cannot
prove deployment-stage action.

Stage age is deployment_runs.current_stage_entered_at, atomic on stage change
including complete; same-stage re-drive preserves age. NULL/no source clock is
unknown, never run-start or source-QA age. Boot adds column without backfill.

## Inbox, shared placement and capacity

Steering-awaiting-seat counts parked role reports/unacknowledged ended-seat
reports; acknowledged never inherits. Acquire shows inherited/parked/stranded
counts and messages-list unacknowledged; JSON keeps newest-by-item digest.
Zero count is omitted. Unacked-injected-this-session rows past grace name
`yoke messages acknowledge MESSAGE-ID`; separate from awaiting-seat inbox.
Every holder appears once in its most specific alarm/landed/live section;
ordinary live-claim inventory is not an idle alarm. Empty sections print nothing.

Single scope adds launchable machine/surface pairs from preview's actual
eligibility, per-surface requested/served model/effort/context counts, origins,
capacity and plan meters. Differing requested versus served remains labelled.
Cursor Models includes grok-*, cursor-grok-* and composer-*; other selections
use Other Models. One CURSOR_MODELS_FAMILIES owner supplies report/preview/
Machines/model-reference split; Claude/Codex name actual vendor counter.
Unreadable meters show reason/recovery from shared guidance: stale_credential
reauthenticates that machine; http_429 means throttled, not signed out; others
retry next refresh. Plan-limit reads never gate launches.

HTTP failed-probe evidence includes status, UTC response time, Retry-After and
safe rate-limit headers in relay log/cached window reason/Fleet row; excludes
credentials/cookies/body. Retry-After is evidence, not changed four-minute cadence.

Levels dry-run actual launch-create --level under seat actor authority, lowest
first with glyph/source project/universe/default. Each option/machine weighed
shows → chosen, ✓ launchable, ✗ blocker/reset/eligibility reason. Pools show
share/headroom/reset, unreadable or no-published-meter. Summary says next
placement/rule/why or no-capacity refusal. Live worker count includes assigned
launches; missing actor shows unavailable/preview command. JSON levels retains
source/live_workers/glyph/chosen/rule/reason/candidates. Item posture level
shift/min/max/reason overrides show once per item; JSON level_overrides retains.

Capacity reads connected relay rows, including capped/unlaunchable machines:
lanes/free GB/load/cores/cap source, AT CAP refusal or unreported/update recovery.
Lane count includes live sessions + assigned not-yet-registered launches; burst
cannot borrow the same slot repeatedly. Eligibility omission never means roomy.

Combined pull prints machine/model/headroom/Test Machine/levels blocks once,
each distinct placement retained; project counts once regardless of seat count.
Scope sections keep work/alarms/claims/model-aware launch balances/origins.
Deployment/landed/mail/unregistered/abandoned project-wide facts merge once
under first project heading; empty document seats collapse to one line and
empty digest headings vanish. JSON retains complete per-scope facts.

## Delivery, fingerprints and pull deltas

Held live seat + interval suffices for empty-inbox model-visible hook delivery,
marked control-plane facts. Message leases do not wait for report composition:
one structured event reply carries envelope; report follows empty hook rather
than holding 30-second lease/ranking or appending unparsable second bytes.
Hook and watcher use same compact digest/closing marker/actionable sections,
own unacked inbox and full-read/help pointer; deliver=true/shared delivered
record prevents reprinting other's report. Worker mail wakes normally; no mail
is still followed by next due hook report.

Undenied/well-formed settlement confirms report survived byte ceiling; denied/
malformed replies consume no delivery interval. Shared last_steering_report_at/
fingerprint compare-and-set suppresses delivered duplicates. A watcher print
racing provisional hook render can duplicate once; later shared identity stops it.

Project-policy defaults: staffing 5 minutes, idle 20, interval 2. Staffing age
starts when pickable: later item change/claim release. Idle is last tool silence,
independent of staffing. One combined composition per interval; changed digest,
including decisions, causes attachment, actionable scopes first.

Fingerprint is age-blind and covers rendered digest: run stage/count/reds/
containment, stranded session/kind/model, project-wide rows once. Full-only live
inventory/balance/placement/capacity/meters/models/relay changes do not wake.
Ordinary delivery-progress states are excluded; native-held is included.
Timed detectors avoid normal claim boundary gaps; positive native death/dead
wait/launch-correlation failure is immediate. Alarms due without delta still
remain alarms. Quiet holder custody never expires from report age.

Human pull defaults to changed held scopes/inbox/unattended/shared-machine
sections + unchanged count. Nullable session-owned age-blind checkpoint survives
calls without telemetry/new table. --full returns all/advances checkpoint; --json
keeps complete facts without consuming it; project filter retains other scope
checkpoints. Hook/watcher intervals use separate existing record. Invalid
checkpoint refuses steering_report_read_state_invalid; get --full replaces it.

`yoke session-control surface-policy disable --project P --machine M --surface S --reason TEXT`
marks one pair; read its --help before mutation. Preview/
create/native wakes skip it with reason/enable recovery, existing sessions stay
up; yoke status lists marks. No auto-trip/probing/counters.

Watcher SIGHUP/SIGINT/SIGTERM reaps child groups and writes interruption/sentinel.
Missing dead-writer sentinel is interrupted; watch tail diagnoses, raw capture
precedes retry. Evidence get FETCH JOB STATE succeeded means file fetched,
not native alive. Unchanged reports stay silent; heartbeat/stall diagnostics
remain raw. Drain complete ready lines before waiting, forward whole report
in one write. Parked release holder awaiting newer candidate remains expected
even after removal from earlier release.

Watcher remembers printed holder/landing/run rows, project facts under stable
lexically-first held descriptor despite actionable reorder. Removed row emits
one in-block no-longer-listed cause (active/parked/released/merged/closed/finished)
from already-read current facts, then forgets it; no sticky rows. Hook-delivered
current report yields only those removal lines. Unknown cause names full report
read; retained PR detail is last observed, never fresh evidence.
