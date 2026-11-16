# Tester Browser Scenario Execution

Execute each listed Browser method case against its live preview environment.

## Select cases

```bash
yoke qa requirement list --item "PREFIX-{N}" --json
```

Select unsatisfied, non-waived requirements whose `method_id` is
`browser-check` or `browser-inspection`. A case's `method_config` is immutable:
never rewrite it; report an incomplete case instead.

You need the preview URL, the lane branch and the deployed lane HEAD SHA. A
missing input is a prerequisite failure; never drop the freshness flags to
force a run. The run needs the item's work claim.

## Run each case

```bash
yoke qa case run \
  --requirement-id <requirement-id> \
  --base-url "<preview-url>" \
  --expected-branch "<lane-branch>" \
  --expected-sha "<lane-head-sha>"
```

The runner records the run, screenshots and traces; never add a run by hand. A
rerun records new evidence. Include the returned JSON and artifact ids in your
report.

| Result | Action |
|---|---|
| `browser-check`, `verdict=pass` | Continue. |
| `verdict=fail` or exit `1` | Report the failed case with its evidence. |
| `browser-inspection`, evidence-backed `verdict=undetermined` | Report it: the item waits for an owner to approve, reject or waive. Never report a pass. |
| `blocked_on_precondition`, `verdict=error` or exit `2` | The case did not run; report it to the scheduler. |

## Read evidence

Read artifacts through their ids, not runner scratch paths:

```bash
yoke qa artifact read --requirement-id <id> --artifact-id <id>
```

A tall full-page capture can shrink past legibility; read one region instead
and name it in your findings:

```bash
yoke qa artifact read --requirement-id <id> --artifact-id <id> \
  --region 0,900,1440,600 --scale 1.5
```

<!-- YOKE:HARNESS cursor start -->
<!-- YOKE:FIELD-NOTE -->
<!-- YOKE:HARNESS end -->

## Important Notes

Report each result with its requirement, run and artifact ids.
