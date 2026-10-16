# Steering report delivery

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [Sessions](index.md) > Steering report delivery
<!-- /yoke:breadcrumbs -->

Inspect delivery waits, deployment runs, shared capacity and report deltas.

## Landed work and dead waits

Landed-without-close-out uses item merged_at or merge_queue_landed_at plus
nonterminal state; control-plane observer records landing even if waiter died.
A parked live release holder with active completion flow reports compact
awaiting-deployment-run or delivering-in-RUN; silence is expected. Missing/gone
holders, aged working holder + landing, unavailable flow, remerged/unreadable
custody or actionable run keeps full detail. Section owns these rows; never
duplicates idle/live holders or members already shown in deployment runs.

Custody batches landing receipt reads and reuses one comparison source per
project and release commit. Definite containment answers for full commit hashes
are cached across requests in bounded process storage, keyed by repository and
commit pair; unknown answers retry. Membership, holder and flow state stay live.

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
share/headroom/per-worker split/reset, unreadable or no-published-meter.
Summary says next placement/rule/why or no-capacity refusal. Live worker count
includes assigned launches; placement splits each pool among the workers on
that machine whose model it covers. Missing actor shows unavailable/preview
command. JSON levels retains
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

Hook and watcher reserve last_steering_report_at before composition, so only one
build runs per window, including denied, cut-off or failed replies. Settlement
records last_steering_report_fingerprint only when the report survived the byte
ceiling. Failed delivery leaves the old fingerprint; the next interval retries.
Watcher replies carry the digest and compact disappearance identities, without
the full body or full scope facts. A skipped window preserves watcher row memory.

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

Fleet activity, launch, message, landing, decision, and report-delivery clocks remain aware instants internally. Report JSON and full clock labels emit fixed-six UTC or null; brief calendar reset labels remain human display. Delivery interval compare-and-set includes the exact native cutoff, preserving microseconds and offset equivalence. A missing clock is unknown; a malformed supplied clock refuses. Earliest landings and latest decision answers compare instants, preserving identity ties and explicit null order.


## Related

- [Steering report](steering-report.md)
