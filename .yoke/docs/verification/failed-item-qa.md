# Recover failed item delivery QA

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [Verification](index.md) > Failed item QA
<!-- /yoke:breadcrumbs -->

The item owner keeps responsibility for failed item-scoped delivery QA.
The release driver arranges delivery; steering ensures the correction has an
owner and that the original owner resumes. A new item never waives failed QA.

## Inspect and classify

Start with the failed result, or the member failure notice's run, stage, item
and requirement ids:

```text
yoke deployment-runs get RUN
yoke qa requirement get --requirement-id FAILED_REQUIREMENT_ID
yoke qa run list --requirement-id FAILED_REQUIREMENT_ID
yoke items dependency list ITEM --json
yoke workflows item get ITEM
```

Record the failed requirement and verdict, run, stage, member, deployed target
and candidate, and diagnosis. The execution's owner already receives its own
result; the failure handoff suppresses a duplicate notice to that session.
A failure discovered by the driver routes to the member's holder, or its
project's steering seat when no holder exists. Read named delivery failures;
absence of a notice does not clear the failed requirement.

- **Product defect:** fix current-item failures in that item by default under
  [verification ownership](../agents/rules/verification.md#verification-failure-ownership).
  Refresh its required survey, take its pinned workflow's ordinary rework
  transition, retain its claim and lane, correct, verify and merge. The driver
  settles the old run without changing its frozen pin; arrange a later run
  containing the correction before retrying delivery QA.
- **Setup failure:** diagnose and repair the environment or runner through its
  existing procedure. Record an explicit blocker while repair is outstanding.
  If the code under test is unchanged, rerun scoped QA on that same deployed
  candidate after setup is restored; retain required cleanup and custody proof.
  A settled roster reprints its verdicts: use the help's `--replaces` recipe
  for a fresh capture of the failed requirement on that same target.
- **Case defect:** repair the case when the product meets the intended outcome
  but the probe does not. Use the [correction-only replacement recipe](deployment-plan-execution.md#shared-plan-credit)
  or `yoke qa plan run --help`; retain the failed attempt and require a passing
  independent verdict on the replacement. Other failed or owed cases stay owed.
- **Unclear cause:** investigate now and retain the failure evidence. Do not
  park on an unnamed future fix or report success from an unproven diagnosis.

For a pinned workflow whose rework stage is `implementing`:

```text
yoke lifecycle transition ITEM --from release --to implementing \
  --reason "Post-deploy QA found a member code defect"
```

## Record a separately owned correction

Use a separate correction only when existing ownership/conflict rules or an
explicit operator decision justify it. Name its owner and item, tell steering
what must be staffed, and write the dependency before waiting:

```text
yoke items dependency add ITEM FIX operator --gate-point closure \
  --satisfaction fact:deployed:ENV --rationale "Delivery QA requires this correction in ENV"
```

Read `yoke items dependency add --help` first. ITEM is the failed dependent;
FIX is the blocking correction. Only ITEM waits. Choose the milestone from
what the retest actually requires:

- `closure` says when the dependent must stop: it may work but cannot complete
  before the condition holds. It does not deploy the fix or select a QA target.
- `status:done` requires the fix item's completion under its pinned workflow.
  Use it when completion is sufficient; it does not require a named environment.
- `fact:deployed:ENV` additionally requires durable completion delivery
  attribution to that registered environment, including its run and candidate.
  Reaching `release`, merging, or merely having a successful run is insufficient.

Do not make the fix wait for the failed item's completion in return.
A `dependency_cycle` refusal names the cycle and recovery; ask steering to
resolve the ordering rather than weakening a real wait. The
[dependency model](../items/model/dependencies.md) owns milestone semantics.

Release composition normally skips dependents of unshipped blockers. Its
existing same-run exception admits both when the blocker is enrolled in that
run or is an eligible candidate shipping with it; a held blocker holds its
own dependents back. This is release admission, not persisted satisfaction or
proof that QA can already see the fix. Confirm the deployed candidate contains
it and the named environment qualifies before retesting. A completed blocker
with the required attribution remains satisfied while siblings wait or fail.

## Checkpoint, retain ownership and resume

Before parking, append the item's Progress Log with the failed requirement,
run/stage/member/target, diagnosis, correction item and owner, exact gate and
satisfaction milestone, retained claim and lane, next command and resume
condition. Keep full evidence in the item's artifacts when needed.

```text
yoke items progress-log append ITEM --headline "delivery QA blocker" --stdin
yoke sessions touch --mode parked --reason "waiting for FIX delivery to ENV for item QA"
```

Park only on an explicit blocker. Keep the work claim and lane; do not end the
session or release ownership to wait. The item's own release wait needs no
self-dependency. When a dependency becomes satisfied, the control plane sends
one notice for that edge to the dependent's holder, otherwise to steering,
naming what cleared and other unmet gates. Coordination-only edges send none.
A notice is evidence to reread, not proof that all current blockers cleared.

On any notice or manual resume, reread the dependency list, current run and
requirement evidence. Check every remaining blocker, including QA outside the
cleared dependency. Then identify the qualifying deployed run, stage, member
and target before executing:

```text
yoke watch qa-plan -- --deployment-run-id RUN --stage STAGE --member ITEM --project P
```

A dependency-cleared notice cannot retarget an old frozen run. If the correction
is absent from that run's lineage, have the driver arrange a later candidate
that contains it and use that run's scoped command. Existing containment guards
may release a corrected member from the old run; preserve its failure history.
An unknown containment result is still a blocker. Never refresh a pin, edit an
endpoint or override a checkout to turn old evidence into proof of new code.
For unchanged code after setup repair or case correction, use the original
qualifying target and the appropriate scoped rerun or replacement command.

## Steering and surfaces without automatic wake

Confirm the diagnosis, correction ownership and milestone; staff the correction
and arrange qualifying delivery. Preserve the original owner's claim. Inspect
failed, deferred or unaddressed failure/dependency/stage notices and the current
member QA status; inspect notice delivery rather than assuming the worker ran.

Read the owner's actual harness manifest's `session_control` and `agent_wake`
capabilities. Queued means stored for delivery, injected means placed in its
receiving context, and acknowledged means receipt was recorded; none alone
proves the session resumed, inspected the target or ran QA. Verify new owner
activity and QA evidence. If its surface cannot wake automatically, arrange an
operator resume of that retained owner with the current scoped command and
checkpoint. Use supported session controls; never teach another harness's wake
primitive as a fallback.

If the owner is unavailable, follow the existing orphan/restaff rules: request
a checkpoint, reconcile/adopt stranded QA as required, and staff a successor
only after the former holder is legitimately released or terminated. Never
seize a live holder's claim. A dependency notice reports satisfaction; steering's
`GO ITEM` instruction authorizes activation after its activation blockers clear.
It is not a substitute for delivery evidence or authority to bypass other gates.
