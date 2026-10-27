# success_policy JSON Schema

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Verification](index.md) > Success policy
<!-- /yoke:breadcrumbs -->

The `success_policy` column on `qa_requirements` records all-pass aggregation.
Each applicable effective requirement must have a completed passing current
actual attempt with current behavioral definition, required review and its own
subject proof. Selection uses aware start instant and id as an equal-start
tiebreak before grading. Historical passing attempts never rescue a newer
pending or failing attempt. See the [requirement state model](requirement-state.md)
and [QA platform](platform.md).

## Item QA across lane commits

The run writer records the item's lane commit at start when available in
`verification_tree.head_sha`, including machine and mission captures. That
commit is an observation only. Later evidence retains it unless the evidence
already names a verified commit; a verified commit is never overwritten.
Merge and done accept the latest completed passing run on the item's effective
requirement without comparing commits. Missing observations, lane advances and
rebases require no new capture or verdict. Required merge-queue CI still tests
the final commit.

Changed configuration or target, missing subject proof, newer incomplete or
failing attempts and required human review still block. Deployment-bound and
post-deploy cases retain their deployed-release proof obligations.

## Stored all-pass policy

Plan cases use the registered policy shape:

```json
{"id":"all-pass","params":{}}
```

Requirement writes accept the bare name `all-pass` and store it as that
object, so every reader decodes the stored value as JSON. A stored value that
is not JSON refuses release admission as `qa_success_policy_unreadable`,
naming the requirement and its correction:
`yoke qa requirement update --requirement-id ID --field success_policy --value all-pass`.

Aggregate requirement metadata may declare `{"kind":"all_pass"}`. Other
aggregation kinds refuse as `qa_success_policy_invalid`. Policies that require
multiple attempts, pass-rate voting or an older high-confidence pass are
unsupported. Correct the policy through its registered authoring surface;
do not waive the resulting missing proof.

## Measurements within one attempt

A method's executable `method_config` may measure exit code, HTTP response,
numeric score, visual metrics or multiple criteria against an expected value
or threshold. Its runner produces that actual attempt's verdict and evidence.
All required criteria must hold for the attempt to pass. A measurement threshold
has no effect on the selection or counting of attempts.

## Human or agent judgment

A reviewer judges the selected actual capture against its expected outcome.
An inconclusive judgment is `undetermined` and retains its rationale and
review evidence. Human escalation resolves the same capture through its exact
resolved decision request. It never creates a newer execution or votes with
older attempts. Final judgments are immutable; changed evidence requires an
actual new attempt.

## Commit proof

Merge verification, release creation (`deployment-runs create` and
`start-for-item`) and the deploy-time CI gate ask the same question: which run
of the `ci_workflow_file` workflow proves this exact commit? It is the newest
run and attempt on exactly that commit whose event is not `pull_request`,
`pull_request_target` or `merge_group` (those test a synthetic merge or a queue
candidate). The branch that started it does not matter, so the run merge
verification dispatched on the item's lane branch proves the identical commit
once it is the gate branch tip, and delivery dispatches no second suite. A
newer failed, cancelled or unfinished attempt is never passed over for an older
green one. Proof is not placement: the bound commit must still descend from the
previous release and contain every member.

A tip with no eligible run at all gets one dispatch on the gate branch at
release creation; repeating the command while that run is in flight reuses it.
`yoke github-actions check-ci REPO WORKFLOW --branch "" --head-sha SHA` reads
the same answer by hand.

## Related

- [Verification](index.md)
- [QA platform](platform.md)
