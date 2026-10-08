# success_policy JSON Schema

The `success_policy` column on `qa_requirements` records all-pass aggregation.
Each applicable effective requirement must have a completed passing current
actual attempt with current behavioral definition, required review and its own
subject proof. Selection uses aware start instant and id as an equal-start
tiebreak before grading. Historical passing attempts never rescue a newer
pending or failing attempt. See the [requirement state model](requirement-state-model.md)
and [QA platform](../qa-platform.md).

## Stored all-pass policy

Plan cases use the registered policy shape:

```json
{"id":"all-pass","params":{}}
```

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
