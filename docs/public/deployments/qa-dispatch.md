# Release QA dispatch

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Deployments](index.md) > QA dispatch
<!-- /yoke:breadcrumbs -->

Read how a release's QA stages reach item owners and the driver, how plan
ownership freezes, how accepted members close, and how dispatch recovers a
lost answer.

## Item QA, run QA and shared QA

A QA stage is scoped to items or to the run. Item QA checks one member with
that item's cases, and the member's owner runs it. Run QA checks the release
as a whole, and only the run's driver answers it. A plan attached by two or
more members is shared QA: it runs once as a driver-owned plan group.

## Gating and wakes

A scoped-QA stage gates every member and wakes waiting members before closing
accepted members. A member held by a QA configuration refusal
(`qa_configuration_refused`) is woken too, once per wait, with the refusal and
its recovery. An item-scoped member also settles when every run-bound item
case has a current pass and evidence, including passes from `yoke qa case run`.
A pending independent review still waits; rerunning passed cases cannot supply it.
Automatic capture also stops when any live case in a plan has a latest `fail`
or `error` verdict. Repeated dispatch cannot open another review for that failure.
A declared `--replaces` correction transfers the obligation to its replacement;
the failed predecessor no longer prevents the corrected case from capturing.

## Frozen member plans

Admission freezes a member's item cases, never its post-deploy plans. A
single-member plan is pinned at item QA entry and runs as member QA; a plan
shared by two or more members is pinned at the run's first group of that
plan ([plan groups](../verification/deployment-plan-execution.md#plan-groups)).
An incomplete frozen item case blocks QA but not removing the member
([removal](removal.md)).

Plan ownership freezes at item QA entry. A plan attached by exactly one member
runs as that member's QA: wake its holder to run `yoke qa plan run --item PREFIX-N
--stage STAGE`. Plans shared by two or more members run as driver-owned plan groups;
run-level QA also belongs only to the driver. Later attachments never change that
ownership. Shared-plan waits, failures and passes send no member-holder notice;
only item QA and close-out wake them. A failed shared plan tells the driver to
triage which attaching items need code fixes and names rework, retry, authorized
waiver and member-removal commands. The notice and fleet recovery name the pinned
commit: Retry reruns that commit for environment/flaky failures; a merged code fix
needs a new run on a later commit that takes over the failed run. Waive discharges
the case; remove leaves the item's delivery owed. Closed groups
credit only their recorded `covered_item_ids` across the superseded-run lineage.
A later attacher gets a new group; already covered items do not wait on it.
The group's pinned cases and target remain authoritative after plan edits.
Run an open group with `yoke qa plan run --deployment-run-id RUN --stage STAGE
--plan PLAN`; the run supplies its project. With no open group, the command
refuses `plan_group_not_open` and names the closed groups. An ambiguous plan
name refuses with the matching plan ids; select an exact id.

## Notices and redelivery

An unchanged wait reuses its notice while its recipient session remains live.
A cancelled notice or an ended recipient permits redelivery to the live driver,
then the run creator, then steering. Closing a group withdraws its old group
notice. The fleet report names waiting requirements and commands, and flags
QA waits with no live driver and an undelivered or unanswered notice.

## Closing accepted members

Each dispatch closes accepted members in order and stops starting more work
after five seconds. A close-out already running finishes; the budget cannot
interrupt it. Each member's route is read fresh immediately before acting, so
an earlier close-out cannot leave later routes stale. A refused close-out
wakes its owner with the refusal and recovery, and the next member is still
tried. The refused member retries by itself when its blocking record settles.
While a member still has a live deployment-stage plan execution, verdict
callbacks defer close-out and send no acceptance or failure notice; stage
settlement closes the member after the delivering execution ends.
A member the budget skipped closes on a later dispatch or at settlement; the
skip never holds the stage.

## Response timeouts

If the idempotent dispatch exceeds its HTTPS response limit, the client waits
for the server's existing reservation and recorded result using the identical
request envelope and request id. It makes up to ten 60-second HTTPS waits,
each within the hosted response cap. It never recovers this timeout through
the self-deploy database door. The server replays a completed successful call;
QA dispatch is also safe to repeat if the original failed before recording a
successful result.

An in-flight copy answers `idempotency_request_in_flight` immediately. HTTPS
result recovery keeps waiting on that same request id within its existing
limit; those replies do not spend the driver's busy retry budget. The driver
also keeps one request id across busy and lost-answer retries for a logical
dispatch. Its next gate check gets a fresh id, so a recorded waiting result
cannot freeze the stage.

Other busy dispatch answers (`run_busy`, `qa_plan_busy`, `qa_checkin_busy`,
`qa_ownership_busy`, `deployment_start_lock_busy`, `deployment_membership_changed`,
`lock_timeout` or `statement_cancelled`) return to the deploy driver's shared
retry policy for every transport. In-process `idempotency_request_in_flight`
also uses this policy. It retries after 15, 30, then 60 seconds, with six
retries total, reusing the same request id. Named check-in, takeover, start and
admission contention is retryable after its transaction rolls back. If every
retry stays busy, the driver stops with `deployment_run_stayed_busy`, leaving
the run and QA stage unchanged; resume with `yoke watch deploy -- RUN-ID` once
the named holder finishes.

An unanswered recovery reports `qa_dispatch_result_unconfirmed`, leaving the
run resumable at its QA stage. Read `yoke deployment-runs get RUN-ID` and the
driver capture before re-driving that same run with `yoke watch deploy -- RUN-ID`. Do not use `--fresh` or the
database door to recover an unknown result.

See [deployment start diagnostics](start-diagnostics.md) for other lost
responses, stage interruptions and bounded QA waits.
