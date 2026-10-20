# Steering fleet report

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [Sessions](index.md) > Steering report
<!-- /yoke:breadcrumbs -->

The server composes reports for the calling session's held steering scopes;
reporting never staffs work. `yoke steering report get` combines them;
`--project P` filters a scope and `--full` retrieves complete detail.
Headings use project slug or `<project> · <document>`.
JSON requests compute every fact; `--json --full` permits the complete reply.
Digest and summary requests skip inventories that they do not render, retaining
plan limits for stranded-session detection. Machine values load once per request
and project membership filters those shared inputs. Session rows name their
person and machine; unavailable identity is explicit, and command IDs stay intact.
Repeated SQL reads share one request-local answer across sections and held seats;
the next report reads fresh state. Waiter, machine-count and candidate-claim
inputs load in sets before classification.

## Scope and available work

Document seats follow item_strategy_docs membership, including execution in
other projects; available work, holders, landing/dead-wait rows and mail to
those holders follow it. Project seats cover unlinked items and CURRENT-PLAN
members. Other-document work with no live seat appears as unattended linked
work with owning project/acquire command. Machines, delivery and unbound
launches remain project-wide/shared facts.

Available work leads: scheduler-runnable unheld rows, ranked, `new` or `stopped`
by prior claim release, `!` after staffing threshold; committed work waiting
only to land prints under `waiting to land` instead. Idle holders still own
their items. Release/completion/cancellation/authorized termination changes
custody; freeze/block hold deliberately; age infers no hold or staffing.

## Holder and landing detectors

| Section | Evidence and response |
|---|---|
| idle holders | No tool call or session heartbeat beyond threshold (watcher wrappers refresh the heartbeat while running; after they stop, ordinary idle timing resumes), excluding proven open queue/armed landing with no failed required checks; merged/dead/unreadable/failed landing returns to ordinary idle rules. Light roster's awaiting-landing fact drives probe; missing fact retains alarm. Full landing details load only when report is due. The watcher's `fleet ALARM idle-holder` also covers parked holders, except one whose item stands at its release wait; it names mode, park reason and message delivery state (unknown when an older roster omits `message_delivery`). A parked holder alarms once; an unparked one repeats hourly until `fleet CLEAR`. Each alarm gets a same-turn action or a one-line disposition saying why the wait is sound. |
| in flight | Quiet running holder inside a budgeted watcher/landing call. Unknown/waiting posture, observed native exit (even clean), denied/closed call, a call overtaken by later activity or one older than 45 minutes cannot excuse silence. Terminal vendor-turn observation survives same-turn tool settlement. |
| landing readbacks | Current nonmutating `yoke github merge-queue readiness PREFIX-N --json`: one status/checks GraphQL read per PR and shared repository/base queue read per request; no cache across reports. |

Landing rows show queue-entry AWAITING_CHECKS/UNMERGEABLE/MERGEABLE/absent/unreadable
and arming. GitHub consumes autoMergeRequest when an entry forms: null arming
with entry means consumed/in-flight; absent entry plus null arming means cleared
and `!`. Entry decides liveness, not null arming alone.

  **The delivery is still on its way** in three, all of which end in *waiting* and none of which is a failure. *delivery attempt in flight* is an accepted resume that has not settled either way. *queued for the recipient's next hook* is the ordinary case: no attempt is owed yet, because a hook has run since the send or the plane is still inside one poll of its own window. *recipient turn in flight since a fixed-six UTC instant* is a recipient whose latest `session_tool_calls` row is still open — the envelope lands on that call's own hook. A live open call defers automatic message wakes even when its activity ages past the stale or idle threshold; that age does not authorize a second turn. Returning from the call delivers through the existing hook. A verified native exit, or a park stamped after the call started, retires an orphaned call, ended sessions retain their supported recovery route, and explicit operator wakes retain their intentional semantics. None of these three borrows desktop *waiting for the operator to wake it* copy: a session that is already firing hooks, or sitting inside a call, is not waiting on a person who has not typed. A row that is open is only the half of that a clock can see; the other half is the state below, which the recipient's own machine reports rather than this one inferring it. These three are reported and never count toward `actionable`, and they are deliberately excluded from the report's fingerprint: every ordinary send passes through one of them, so hashing them would turn routine fleet traffic into changed-report wakes for mail about to land by itself. Reporting any of them as a failure sends the seat after a delivery already under way, and this section formerly dropped all three, which left a seat unable to tell an attempt in flight from one that had never been made.
Parked holders are expected waits unless native death is proven. A stopped turn
with unfinished call is immediately idle (declared park remains a wait).
Holder rows describe delivery rather than infer native liveness:

- `mid-turn — message waits until the turn ends` from running turn posture;
- `between turns — message wakes it` from waiting posture or a recorded exit,
  on surfaces whose manifest declares `message_stopped`;
- `parked waiting on X` from the holder's declared park reason, whether its
  native remains alive or exited normally;
- a wake already underway says `message wake in flight — let the turn start`;
- surfaces without stopped-message support name the need for operator input;
- unavailable posture says `delivery state unknown — inspect session evidence`.

Containment keeps its recorded reason visible, including when the native
returned zero: a sweep kill is abnormal and a park cannot hide it.
Exhausted/rejected/unavailable-model cases go to stranded.
The session roster exposes the same server-composed `message_delivery` for
fleet idle-holder lines; an older server without that field reports unknown.

`yoke sessions terminate` refuses TERMINATION_RESUME_IN_FLIGHT unless
--allow-resume-in-flight. sessions.list native_process exposes resuming with
resume_started_at, or gone with resumable_from_transcript. Ended/terminated
sessions are excluded from holder alarms; a live unparked idle holder re-alarms hourly.

## Undelivered messages

Rows group recipient + delivery state, count, up to three ids and oldest age.
Live/resumable recipients use the delivery plane's deliverable-receipt predicate.
Ended recipients without a remaining route also report pending/injected receipts
still awaiting acknowledgement; settled, expired or cancelled mail stays out.
Message visibility applies; confirmed current/recent item attribution retains
document coverage after claim release. Sender is not a filter; bodies stay private.

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
not deliver content. Read `yoke messages get MESSAGE-ID`, handle or re-address
the work, then cancel obsolete mail as sender actor or target-project admin.
Report composition never acknowledges, cancels, reruns QA or gates worker exit.

Queued explicit wake with no attempt names `yoke session-control session wake
SESSION-ID` only after every receipt reaches its own acknowledgement grace.
Before then it reports releasable-at timestamp and no command; a younger queued
receipt still causes wake_in_flight. A single failed attempt overtaken by a
live call may defer; repeated failures retain precedence.

Native-held rows name the native and, when measurable, its no-output age from
the capture's own clock, not periodically refreshed file mtime. Missing old
clock means unknown, never recent output. Parked declares wait, not exit; a
supervisor-recorded exit ends the hold despite surviving group members. Codex
background_session_in_use is native_turn_running deferral, not a failure.
Observed exit reopens a busy receipt even at retry limit; silence cannot reopen
an exhausted unparked one. Verified exit or a later park retires orphan open calls. Explicit
operator wake keeps its semantics; automatic wakes never start a second turn.

wake_escalation qualifies actionable rows: starved_hook_route,
parked_without_idle_wake, native_process_gone. These escalate at once; later
activity retires observations. Clean exited parked/landing workers resume
their stored native identity on their next message; their wait stays expected.
Machine observation, not heartbeat age, proves exit. Escalated rows name
`yoke session-control session wake SESSION-ID`; terminate needs transcript gone.

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
[machine-local-evidence.md](../databases/machine-local-evidence.md).

## Stopped sessions and launches

Vendor-stopped rows use stored native turn record on readable-manifest surfaces,
persisting provider words/classification/time and HarnessSessionTurnEndObserved
telemetry. Stored recovery survives telemetry retention. Turn-end-hook surfaces
already settled and declare that reason. Recoverable capacity, client-build
and HTTP 429 throttle (`rate_limited`) refusals retry with widening bounded
backoff; show next attempt/time. A named usage limit (`quota_exhausted`),
rejected credentials or exhausted retry budget need seat action; only those
rows are actionable.

Stranded sessions cannot resume: exhausted published model pool (included
zero and fresh paid extra usage disabled, cap reached or unfunded), rejected
credentials or removed model. Show count/items/relaunch on available headroom,
never automatic model substitution/wake. Preferred-default drift is not a wall;
still-registering sessions within deadline are excluded. Unknown/unreadable
meter is not exhaustion; only that model's own zero pool is, and only when
extra usage cannot cover it. Extra usage available, unknown or stale lets the
wake run and the provider decides. Wake refuses meter_exhausted with
remaining/reset and the extra-usage phrase; recurring resumed-died may project
blocked-meter-exhausted. The plan-limit table ends with one `extra usage ·
machine · surface:` line per surface, and JSON rows carry `extra_usage` and
`extra_usage_label`.

Unregistered launches report immediately for failed correlation or exact
active harness session lacking binding; otherwise after deadline_at. Deadline
starts at pickup, not queued time. State that mandate was not delivered;
reconcile before retry. Live native: bind it; exited native: reconcile/retry,
with exit/last line and session evidence read. Exclude unrelated closed history.
Abandoned launch: delivered mandate but no claim/outbound message/completed
call, native gone; show session/closed age/exit/last line, restaff unstarted work.
Rows expire after six hours.


## Related

- [Steering report delivery](steering-report-delivery.md)
