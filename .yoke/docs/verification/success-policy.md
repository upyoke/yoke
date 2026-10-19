# success_policy JSON Schema

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [Verification](index.md) > Success policy
<!-- /yoke:breadcrumbs -->

The `success_policy` column on `qa_requirements` records all-pass aggregation.
Each applicable effective requirement must have a completed passing current
actual attempt with current behavioral definition, required review and its own
subject proof. Selection uses aware start instant and id as an equal-start
tiebreak before grading. Historical passing attempts never rescue a newer
pending or failing attempt. See the [requirement state model](requirement-state.md)
and [QA platform](platform.md).

## CI across candidate commits

After a rebase, run `yoke qa case run --requirement-id ID` for the current
candidate. A newer completed passing `command-ci` requirement on that exact
candidate covers older passing CI requirements whose only refusal is their
earlier recorded commit. They must belong to the same item, workflow transition
and verification phase; the covering requirement and its run must both be newer.
The original requirements and runs remain readable history, with no waiver.
Without a current pass, merge still names each stale requirement and its repair.
Missing commit proof, changed configuration or target, incomplete or failed
attempts, human review, deployment-bound cases and other methods keep their
own obligations.

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

## Related

- [Verification](index.md)
- [QA platform](platform.md)
