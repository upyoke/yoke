# Release-time roles

<!-- yoke:breadcrumbs -->
[Yoke](../../index.md) > [Agents](../index.md) > [Operation homes](index.md) > Release roles
<!-- /yoke:breadcrumbs -->

Read this home before configuring release identities or role grants; it explains the permissions each release action needs.

## Release-time roles

A run that carries members is acted on by two different sessions, and neither
learns the other's part from its own skill. The split is the whole rule:

- **The seat driving delivery owns the run.** It pins one source SHA, creates
  the stage and production runs from that SHA, and starts each one with
  `yoke --env CONTROL-PLANE watch deploy -- RUN-ID`. On a flow that waits for CI the SHA must have its own
  run of the project's `ci_workflow_file`: a merge-queue push tests only its
  newest commit. Create the CI-gated run (production) without `--source-ref`
  and it binds the newest commit on the gate branch's first-parent line whose
  own branch run (never a merge-queue or pull-request run) passed or is
  running — or, when none has one, dispatches that workflow on the branch and
  binds the commit the dispatched run tests. A selected commit that does not
  descend from the lineage the previous succeeded run shipped to that
  environment is refused `release_source_off_lineage`, naming both commits;
  pin a descendant with `--source-ref`. Give the paired stage run that
  `release_lineage` with `--source-ref`; stage refuses a missing lineage. An
  explicit commit with no run of its own is refused
  `release_source_untested` on every path that binds one, naming the newest
  tested commit. These reads use the project's GitHub App access scoped to
  `actions: read` and `contents: read` (a private repository's commits need
  the second); a read GitHub refuses for authorization is
  `release_source_unverifiable` naming that access and its repair, never a
  retry. The CI gate itself never dispatches CI: a release commit
  with no run of its own fails it by name, and the recovery is a new run. Creation provisionally enrolls every delivery-ready item
  its candidate carries that no live or succeeded release already holds —
  whether the work landed since the last release or long before it — and
  validates before committing the run. Start revalidates before dispatch, so
  membership needs no separate step. The pipeline checks member ancestry and
  squash-merge evidence against the run’s frozen `release_lineage` commit,
  independent of local deploy-branch refs. A missing member blocks with
  `release_member_not_in_source`; merge it and compose a new run containing it:
  `yoke deployment-runs add-item RUN-ID PREFIX-N` is for the other case, an
  item whose code the candidate does not carry but which the run should still
  deliver, and `validate-composition` composes the run now and reports what
  it enrolled or why it refused. One notice names every carried item it
  skipped and why: held by another release, back in rework (status before
  its release stage), removed, or blocked by an open dependency on an unshipped
  item. Composition skips that dependent until its blocker ships or reaches
  done. Completion dependencies read the item's done milestone; explicit
  environment dependencies also read its persisted delivery attribution.
  Completed members remain satisfied while siblings wait, fail or cancel.
  For incomplete blockers the notice names the holding run. The first
  subsequent release enrolls it, including landings below
  the prior release baseline. Satisfied and coordination-only edges do not
  delay enrollment. Workers finding blocked item QA record the dependency
  with `yoke items dependency add DEPENDENT BLOCKER operator --gate-point
  closure --satisfaction status:done --rationale R`; read its `--help` for
  direction and named-environment delivery facts. A wrongly composed member of a run still
  `created` comes out with `yoke deployment-runs remove-item RUN-ID PREFIX-N
  --reason R`: the reason is recorded on the run,
  removal also aborts this run/member's live QA executions and releases queued
  host reservations and held leases in the same transaction. A removed member's
  holder may abort its own leftover execution with `yoke qa plan abort
  --deployment-run-id RUN --execution-id ID --reason R --project P`; read its
  `--help` first. Composition never re-enrolls it, its code still ships, and a later release
  enrolls it; `add-item` reverses the removal while created. Unsettled independent members may also be removed while executing at item QA or failed at `item-qa-failed`, with the same shared-gate guards: every unsettled run-bound requirement of the member is retracted whatever its verdicts, keeping its run history; standing plans remain. A live item QA runner skips a member only when its membership row is absent and the run records its removal, then continues the remaining members; an unrecorded missing member still fails loudly. Resume the failed run with `yoke watch deploy -- RUN-ID --from-stage item-qa`; every other failed stage still refuses removal. Before creating a release pair, inspect the
  delivery-ready items' selected completion flows and choose their flow. A
  refused creation or start names independent blockers together, including
  each mismatched member flow. Use a run of the
  selected flow, or deliberately reconcile item flows, then revalidate;
  never silently change an item's flow. An item a cancelled run left behind
  needs no attaching, and `yoke steering report get` names any landed item no
  release holds so nobody has to notice one going stale. The driving seat does
  not run a member's item QA and does not close a member out.
  Deployment-run cards exclude recorded removals from carried counts and
  member QA. A separate Removed section says "QA cancelled — rides" and names
  the newer run holding the item, or "a later release" when none holds it yet.
  For red member QA, `yoke deployment-runs remove-item RUN ITEM --reason R` lets an independent run finish while the member waits for its next release; see `remove-item --help`. Failed independent item QA automatically releases a member whose recorded merge is definitely outside its project's frozen lineage, using the same audited removal as settlement; unknown containment holds and reports recovery. Settlement also releases replaced candidates.
- **Commits made outside Yoke ship without an item.** Composition never
  blocks on commit ownership. Carried work records each commit's SHA, subject
  and author under its project. Run pages, Shipping cards, Runs tables and
  release approvals show "Also includes N commits made outside Yoke", with an
  expandable commit list. Optional `yoke merge-receipt commits attest PREFIX-N
  --commit SHA --reason R` ties this item's work to its receipt; read `attest
  --help`. Installer refreshes follow the same rule as any other outside commit.
- **The attach says what the run can do for the member.** Two independent
  capabilities: a run **checks** a member only through an item-scoped QA
  stage, and **closes** one only as that item's completion flow or as another
  project's run carrying this project's source. Most delivery flows check
  nothing and close everything they carry, so a missing item-scoped stage is
  no reason to refuse an attach — but a run that can do neither gives the
  member nothing, and membership still holds the landing, so the next start on
  the item's completion flow will not enroll it. `add-item` names that case
  with the flow that can close the item; `validate-composition` names any
  member already in it. An item-scoped QA stage proves each member against
  the requirement snapshot the composition freeze writes, and only a flow
  that takes delivery custody freezes one: creation, `add-item`, and
  `validate-composition` refuse a custody-free run that carries or owes
  members (`item_qa_flow_without_delivery_custody`). A memberless run is
  judged by what it owes: `validate-composition` and the pre-execution check
  refuse it, before any stage deploys, when its flow is the completion flow
  for delivery-ready items no other release holds
  (`item_qa_run_without_members`). Holding is landing custody, as enrollment
  reads it: a re-merged landing, an unreadable one, or one held only by a
  supplemental stage run is still owed, and an unreadable completion flow
  refuses as `item_qa_owed_delivery_unreadable`. Otherwise — a stage run whose
  candidates were targeted out — its item-scoped stage passes with the named
  `item_qa_no_member_owes_target` result. Dispatch, the outstanding report,
  and later stages' prior-acceptance check ask the same question again and
  fail closed rather than trusting the pre-start answer. Creation does not ask the member
  question, because it mints itemless runs for `add-item`.
- **The member owner owns its own item.** Its merge parked it at the flow's
  release wait holding its work claim, and the close-out block names what the
  item owes delivery and whether the owner's surface can be woken. On a
  natively wakeable surface the deployment wake re-enters it for its QA stage
  and when its own item-scoped QA clears; a surface whose wake authority is
  operator (a desktop app) is never resumed by Yoke, so its operator or a
  steering seat re-enters it. An item owing nothing closes on delivery with
  no re-entry. A final member on a
  selected flow without run QA or run approval closes after its own final production QA is
  accepted or discharged by `post_deploy_no_obligation` or a waiver-backed
  item declaration, provided no run-bound blocking obligation remains, even
  while sibling QA holds the run open. Run QA or run approval holds
  every final member through all item QA, shared gates, and run success. This
  automatic close-out needs no delivery wake and ends an otherwise empty
  holder session. Legacy schema-1 settlement and the terminal done gate credit the run's run-wide
  post-deploy requirements to its delivered members without source keys; scoped runs keep exact private-member or attached shared-plan binding. Failing or unanswered requirements block, and superseded
  requirements follow their successors. A wait wake is withdrawn — the
  existing message-cancel path —
  when its run reaches a terminal status or its member is no longer
  outstanding (the item-scoped stage is credited, or the item is done), so
  a late delivery cannot instruct settled work. Recorded delivery attempts
  stay as evidence. A wake whose every attempt in a bounded window met the
  same non-transient condition (a native turn that never exited) escalates
  on the receipt and names that condition, rather than retrying in silence.

**A QA stage credits only requirements bound to its own stage name** — an
item-scoped stage reads the member's private cases and attached shared-plan groups. So the member owner runs
`yoke qa plan run --deployment-run-id RUN --stage STAGE --member PREFIX-N`, and
the unscoped run-wide form is refused rather than recording a pass the stage
ignores. `yoke qa case run --requirement-id N` credits that requirement's
existing binding and never a stage, so it cannot substitute either: when the
requirement is already bound to an item-scoped stage it refuses and names
the plan-run invocation that would credit it. Dropping `--stage` or
`--member` is the failure that looks like success: every case passes and the
stage still reads unsatisfied.

**`yoke merge item` is the one agent-facing close-out**, at the merge and again
at the release wait, carrying `--result` and `--verification` both times. There
is no internal done engine to substitute: `done-transition --skip-deploy`
records a selected-flow delivery as out-of-band, which is a false record and is
refused once that flow has a succeeded run covering the merge. It remains only
for a flow that genuinely delivers nothing.

Each of those commands carries the full matrix in its own `--help` — that is
the deep home for this section, and it is the one that cannot go stale against
the code: `yoke qa plan run --help` (subject/scope matrix), `yoke qa case run
--help` (which credit it cannot earn), `yoke merge item --help` (close-out
routes and the queue landing handoff), and `yoke deployment-runs --help` (the
item-bound batch release, plus the itemless environment release).

## Related

- [Deployment runs and packaged capabilities](delivery.md)
- [Pack capabilities](packs.md)
