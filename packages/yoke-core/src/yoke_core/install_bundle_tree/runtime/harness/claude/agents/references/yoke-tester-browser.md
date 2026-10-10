# Tester Browser Scenario Execution

For a dispatch **Browser Scenario Execution** block, execute every listed
Browser method case against its live ephemeral environment.

## Select and authorize cases

```bash
yoke qa requirement list --item "PREFIX-{N}" --json
```

Select unsatisfied, non-waived `browser-check` / `browser-inspection`
requirements by `method_id`, never `qa_kind` or item metadata. Materialized
snapshots are immutable: `method_config` supplies steps and optional case-local
URL. Do not refine, replace, or otherwise rewrite `method_config`.
Report an incomplete contract instead.

Require all dispatch inputs: ephemeral URL, resolved worktree branch, deployed
worktree HEAD SHA. Missing input is a prerequisite failure; never remove
freshness flags to force execution. Item claim and ambient session must be active.

## Execute each requirement

```bash
yoke qa case run \
  --requirement-id <requirement-id> \
  --base-url "<ephemeral-url>" \
  --expected-branch "<worktree-branch>" \
  --expected-sha "<worktree-head-sha>"
```

Shared runner authorizes/fetches through `qa.case_execution.begin` before
Browser startup, runs only this requirement, and owns its run/screenshot/trace
records. Never manually add another run. Reruns create new evidence runs,
without changing snapshots. Include returned JSON and artifact paths in report.

| Result | Action |
|---|---|
| `browser-check`, `verdict=pass` | Continue. |
| `verdict=fail` or exit `1` | Report failed case and product/environment evidence. |
| `browser-inspection`, evidence-backed `verdict=undetermined` | Report the request; item halts until owner/operator approves, rejects or waives. Never report pass. |
| `blocked_on_precondition`, `verdict=error` or exit `2` | Case did not run or runner failed; report to scheduler, without requesting human review of missing evidence. |

## Read evidence through its recorded identity

Runner scratch paths are outside claimed-lane read authority. Use artifact ids:

```bash
yoke qa artifact read --requirement-id <id> --artifact-id <id>
```

Read whole capture once to select relevant pixels. Tall full-page images may
scale illegibly; inspect the region rather than judge a blur:

```bash
yoke qa artifact read --requirement-id <id> --artifact-id <id> \
  --region 0,900,1440,600 --scale 1.5
```

`--region x,y,w,h` is the rectangle from top-left; scale multiplies size after
cropping. Stored artifact stays intact. Response names rendered `artifact_view`;
name the judged region in findings. Out-of-image rectangles refuse with image size.

<!-- YOKE:FIELD-NOTE -->

## Important Notes

Report the evidence-backed result with its requirement/run/artifact identity.
