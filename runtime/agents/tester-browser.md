# Tester Browser Scenario Execution

When the dispatch prompt includes a **"Browser Scenario Execution"** block,
execute every listed Browser method case against the live ephemeral
environment.

## Select the cases

Read the materialized requirements:

```bash
yoke qa requirement list --item "PREFIX-{N}" --json
```

Select each unsatisfied, non-waived requirement whose `method_id` is
`browser-check` or `browser-inspection`. Method identity selects Browser
execution; do not infer it from `qa_kind` or item metadata.

Each requirement is an immutable materialized case snapshot. Its
`method_config` contains the declared steps and optional case-local base URL.
Do not refine, replace, or otherwise rewrite `method_config` during testing.
If the case contract is incomplete, report that specification failure instead
of changing the case under review.

## Require the deployed code identity

The dispatch block supplies all three execution inputs:

- the ephemeral URL;
- the already-resolved worktree branch;
- the already-resolved worktree HEAD SHA deployed to that environment.

Treat a missing URL, branch, or SHA as a prerequisite failure. Never omit the
freshness flags to make a Browser case run.

## Execute each requirement

Run the shared case runner once per selected requirement:

```bash
yoke qa case run \
  --requirement-id <requirement-id> \
  --base-url "<ephemeral-url>" \
  --expected-branch "<worktree-branch>" \
  --expected-sha "<worktree-head-sha>"
```

The runner authorizes and fetches the immutable case through
`qa.case_execution.begin` before starting the Browser substrate, executes only
the named requirement, records its run, and stores screenshot and trace
evidence. The item claim and ambient session must already be active. Do not add
a second run manually.

## Interpret the result

The runner prints JSON. Include the result and artifact paths in the validation
report.

| Result | Tester action |
|--------|---------------|
| `browser-check` with `verdict=pass` | Continue. |
| `verdict=fail` or exit `1` | Report the failed case and product or environment evidence. |
| `browser-inspection` with `verdict=inconclusive` | Report the generated review request; the requirement remains unresolved pending approval, rejection, or waiver. |
| `verdict=error` or exit `2` | Hard-stop on the prerequisite or executor failure and report it to the operator. |

Re-running the same requirement creates a new evidence run. It does not mutate
the case snapshot.

<!-- YOKE:FIELD-NOTE -->

## Important Notes

- Method identity selects Browser execution; never infer it from legacy
  requirement kinds or item metadata.
- `yoke qa case run` owns the run and its evidence records; never add a second
  run manually.
- Browser inspection remains inconclusive until a reviewer approves, rejects,
  or waives it; never report that state as a pass.
- The ephemeral URL, deployed branch, and deployed commit are mandatory
  freshness inputs.
