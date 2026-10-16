# Requirement discharges

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [Verification](index.md) > Requirement discharges
<!-- /yoke:breadcrumbs -->

Derive requirements from acceptance criteria and settle obligations through explicit waiver, supersession or retraction.

## AC-Derived Requirements and Suite Graduation

ac_derived records an AC-derived case. Nullable suite_id links future stable
suite membership: define AC, derive case, graduate a stable case to a suite.
The metadata itself is no passing result.

## Discharges: waiver, supersession, and retraction

Discharge is recorded and satisfies gates, while staying distinguishable from
pass. Failed/error admitted cases on a named stage can be corrected (never a
passed/no-verdict case): author only the corrected case and execute:

```text
yoke watch qa-plan -- --deployment-run-id {RUN_ID} --stage {STAGE} --member PREFIX-N --plan {CORRECTED_PLAN} --project {PROJECT} --replaces {CASE_KEY}={FAILED_REQUIREMENT_ID}
```

Materialization/declaration commit together; old failure remains history,
corrected blocking case and pending siblings still need proof. Interrupted
re-entry reuses declaration. Existing direct correction can be declared with
qa.requirement.supersede --declare-replacement, then scoped plan execution
without --plan. Predecessor leaves roster; successor still must pass.

**Waiver:** qa.requirement.waive stores waived_at/rationale/source; blocking
needs --force. Operator decides. Recording --source operator for item/member
needs its item claim, a covering steering seat (including document membership),
or the live driver of the run holding it. Steering can record the rationale while
worker keeps item custody; re-drive that run. Another run's driver or an unrelated
item grants nothing. Agent waivers keep normal QA subject-claim authority.
Read `yoke qa requirement waive --help`.

**Supersession:** corrected blocking case needs same run/stage/member/target
(item: same item/transition/phase/target) and its own qualifying pass. History
is untouched. Declared replacement via plan run/materialize --replaces records
replacement_requirement_id after same-scope/acyclic validation. Predecessor
immediately leaves grading/roster; only terminal successor answers, even pending
or failing. Review bundle includes newly captured cases only. Independent pass
(agent review or human approval) supersedes in that verdict transaction; fail/
undetermined supersedes nothing. Content refresh declares correction automatically;
qa.requirement.supersede can declare one explicitly.

**Retraction:** qa.item-plan.retract withdraws a mis-specified unexecuted item
attachment at any phase; retain attachment/requirements as retracted history, not waiver or
supersession. Item becomes unanswered. Done/member/freshness readers exclude
withdrawn obligations; summaries keep RETIRED/retracted_at history. Admission
and frozen selection skip withdrawn attachments; replacement plan owes proof.
For older frozen copies, repeat with item/project/plan-id/transition release/
reason: retires remaining copies, preserves original withdrawal, refuses any
copy with a recorded run or verdict. Re-drive scoped QA/run. Preserve recorded
evidence and use waiver or supersession to settle executed cases.

Waiver/supersession answer every gate, including Dash verification/close-out.
Supersession still needs current same-candidate pass within accepted revisions
(including current reworked lane head); unfinished successor names owed evidence.
Deployment acceptance and done honor admitted discharge and validated same-scope
member supersession after stage acceptance. Unsettled failures keep done blocked.

Run-local supersession never retires its item source: an outstanding source
would be admitted again. Receipts name admitted_from_requirement_id and
next_admission_notice only while that source is outstanding; absent/discharged
sources get neither. Retiring a post_deploy item source is explicit:

```text
yoke qa requirement add --item PREFIX-N --target-env {ENVIRONMENT} --method-id {METHOD_ID} --qa-phase post_deploy --blocking-mode blocking --workflow-transition {TRANSITION} --instructions-file {INSTRUCTIONS_FILE} --expected-outcome-file {EXPECTED_OUTCOME_FILE} --method-config '{METHOD_CONFIG_JSON}'
yoke qa requirement supersede --requirement-id {SOURCE_ID} --superseded-by-requirement-id {CORRECTED_ID} --rationale "corrected source definition"
```

Declare the corrected body through requirement-add's --help contract for the
same item/transition/phase/resolved environment; snapshot digest may differ.
Neither source executes. While a run the item still belongs to holds an
admitted source copy, require one replaced or superseded through a chain whose
terminal case has a current config/target-qualified pass. Receipt names
run_replacement_requirement_id. That case still answers its run; corrected
source reads retired source's admitted copies at done. When no live membership
holds a copy (item removed with `yoke deployment-runs remove-item`, run failed
or cancelled, or never admitted), retirement records the link and the receipt's
proof_owed_notice says the corrected source owes its own next-release proof. Later
admissions skip superseded source and admit corrected one; source is never
rewritten. Control plane may record an authorized target it cannot execute
(prod recording stage); execution alone checks runtime observation authority.

All blocking cases discharged → subject reports discharged, accepted for gating
but distinct from accepted passing proof. A carried cross-project member owes
no item QA only when its own completion flow declares none and no explicit
plan/post-deploy requirement exists; report names that flow, records no answer
and closes with run. Same-project/QA-owning carried members still owe proof.
No cases otherwise means unanswered, except recorded no-post-deploy-obligation
or waiver-backed declaration. `yoke qa post-deploy record-no-obligation` is not
a waiver. Read `yoke qa plan run --help`.

## Related

- [QA platform](platform.md)
- [Requirement state](requirement-state.md)
