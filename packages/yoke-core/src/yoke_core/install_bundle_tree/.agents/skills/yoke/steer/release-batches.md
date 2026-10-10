# Steer — batch delivery of verified merged work

Workers merge, never create/dispatch runs. Steerer uses prod control plane even
for stage target; ordinary external delivery is HTTPS. Yoke self-deploy first
reads [source-dev-delivery.md](source-dev-delivery.md).

## Hold and compose exact code/selected flow

```text
yoke claims coordination-claim acquire --project {_project} --key DEPLOY:{_project} --reason "driving the release pair"
yoke items get PREFIX-N deployment_flow project --json
yoke deployment-flows stages {FLOW}
```

Hold DEPLOY before creation/execution through the whole declared release.
Read each selected flow/bound projects; same-project final delivery uses its
member flow. Cross-project carrying run closes only recorded bound source it
actually ships. Differing selections need their selected run or deliberate
reconciliation+composition validation, never silent rewrite.

Pin one CI-proven SHA for stage/production. CI-gated production create omits
source-ref: newest tested first-parent on gate branch, or its dispatched CI
candidate if no run exists. release_source_off_lineage/untested refuses with
actual commits; unresolved gate names recovery through new run, not hand dispatch.
Read production release_lineage and give stage that exact source; missing lineage
refuses. Other projects retain declared stage ordering.

```text
yoke --env CONTROL_PLANE deployment-runs create {_project} {PROD_FLOW} --environment prod --idempotency-key PROD_KEY
yoke --env CONTROL_PLANE deployment-runs get {RUN_ID} release_lineage
yoke --env CONTROL_PLANE deployment-runs create {_project} {FLOW} --environment {ENV} --project-repo-path {CHECKOUT} --source-ref {PINNED_SHA} --idempotency-key STAGE_KEY
yoke --env CONTROL_PLANE deployment-runs validate-composition {RUN_ID}
yoke --env CONTROL_PLANE watch deploy -- {RUN_ID}
```

Creation freezes source and provisionally composes candidate-carried ready items
not held by live/succeeded release, including earlier landings. Validation
refuses independently detectable blockers before run id; start validates again.
Skipped held/rework/removed members are named. Production holds prod; exact same
SHA stage still enrolls owed stage QA, other SHA skips with pinned commit named.

Input_bindings resolves another registered project's branch once at composition
and freezes its commit. Membership follows actual carried code: merged after
binding resolution needs another run, project with no bound source refuses.
Read stages before planning either project's delivery.

```text
yoke --env CONTROL_PLANE deployment-runs add-item {RUN_ID} PREFIX-N
yoke --env CONTROL_PLANE deployment-runs remove-item {RUN_ID} PREFIX-N --reason REASON
yoke --env CONTROL_PLANE deployment-runs create {_project} {FLOW} --retry-of {RUN_ID} --idempotency-key RETRY_KEY
```

Add is intentional noncarried member only under same hold/created run, valid
project/source/flow. Mistaken created membership removes with recorded reason
and no auto re-enroll, not pair cancellation. Red member QA removal can release
an independent run under remove-item --help's lineage/removal evidence; never
pretend candidate code is absent. Settlement releases members whose current
candidate is outside the frozen lineage, through its recorded authority.

Yielded create still runs: continue its handle. Only exited-without-id retries
verbatim SAME key to recover original; new key deliberately means new run.
Retry copies frozen sources: bound-source stale failure requires new composition,
neither re-drive nor retry-of changes its commit. Preserve run history.

## Member and run QA are distinct ownership

Member owner runs exact stage+member requirements after its deployment wake.
Operator-wake desktop requires that operator; don't resume it natively. A live
holder stays owned, never acquire its claim or run its QA for it.

```text
yoke watch qa-plan -- --deployment-run-id {RUN_ID} --stage STAGE --member PREFIX-N --project {_project}
```

Broadcast this form, not unscoped qa plan or requirement-only qa case: those
cannot credit stage/member. Add --plan PLAN only if stage names no cases.
Correction-only plan may name --replaces CASE_KEY=FAILED_REQUIREMENT_ID even
for admitted cases; supersession occurs when reviewed correction passes,
never manual replacement. System-owned missing wake is a defect to repair.
Accepted scoped QA opens configured review; settled/red/continuation failure
notifies driver, individual member while others owe stays in report. Re-drive
same pinned run after notice without replaying passing stages.

Driver owns run-scoped visual inspection (or explicitly assigned capable QA):

```text
yoke watch qa-plan -- --deployment-run-id {RUN_ID} --stage STAGE --project {_project}
```

Same optional-plan/correction rules apply. Member evidence cannot credit this
run subject. Re-drive pinned runner afterward.

## Automatic selected-flow close-out and orphan recovery

Without run QA/approval, final member closes from landing plus its own final
production QA or explicit post_deploy_no_obligation discharge while siblings
can still hold run. With run QA/approval all final members wait for every item
gate/shared gate/run success. Bound-source carrying flow owns only source it
ships. Automatic close-out ends otherwise empty holder; no redundant merge
for accepted QA. Refused/interrupted settlement remains executing with owed
claims/lanes; re-drive existing run's settlement, never false succeeded.
done-transition --skip-deploy misrecords selected-flow delivery as out-of-band
and refuses covered success. Never substitute internal done engine.

Only ORPHANED member explicitly handed to seat by stale recovery is yours:

```text
yoke claims work acquire --item PREFIX-N --reason "orphaned release-wait member"
yoke merge item PREFIX-N --result "what shipped" --verification "run evidence"
```

Release only if close-out did not already release. Release-wait path claims/
dependencies remain until done. Final settled release returns DEPLOY:

```text
yoke claims coordination-claim release --project {_project} --key DEPLOY:{_project} --reason "release pair complete"
```

No automatic reclaim. Stranded hold requires signed-in human outside harness,
after pipeline settled, exact claim/holder and recorded reason/WARN:

```text
yoke coordination-claim release --project P --key DEPLOY:P --claim-id {claim_id} --holder-session-id S --reason REASON
```
