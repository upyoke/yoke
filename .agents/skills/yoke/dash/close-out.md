# Dash — close out

Close out with the same merge command, even after a queue landing; never write a terminal status by hand:

```text
yoke merge item ITEM --result "<result>" --verification "<checks/evidence>" --json
```

Delivery owed: keep the claim and lane, send no DONE, and park whenever quiet:

```text
yoke sessions touch --mode parked --reason "awaiting ITEM delivery: deployment run, then post-deploy validation and the done close-out"
yoke watch qa-plan -- --item PREFIX-N --stage STAGE --project P
```

Exit 12 is a capture awaiting review: dispatch the returned review bundle and submit it. Use `--plan` to select an already admitted frozen plan or to replace failed cases explicitly.

Rework after landing: register the fresh touch set (`yoke claims path register --item ITEM --paths ... --allow-planned`) when claims are selected, prepare the lane, then move back:

```text
yoke lifecycle transition ITEM --from LIVE_STAGE --to REWORK_STAGE --reason "required rework: <correction>"
```

Approval-on-done: wait for the owner's decision, then resume.

Report this session's guardrail denials (file field notes for any unrecorded):

```text
yoke events query --session SESSION_ID --event-name HarnessToolCallDenied --json
```

At a terminal status: report to `yoke say --steering`, then release a claim that remains:

```text
yoke claims work release --item ITEM --reason "Dash completed"
```

## Laneless

```text
yoke direct-workflow dash evidence ITEM --result "<finding>" --verification "<observed proof>" --no-changes --json
```

Then walk each declared forward edge to a terminal stage with `yoke lifecycle transition`. A lane with no changes uses `yoke merge item --no-changes` instead.
