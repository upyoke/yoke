# Dash — close out

Delivery owed: keep claim and lane, and park whenever quiet:

```text
yoke sessions touch --mode parked --reason "awaiting ITEM delivery: deployment run, then post-deploy validation and the done close-out"
yoke watch qa-plan -- --deployment-run-id RUN --stage STAGE --member PREFIX-N --project P
```

Report `HarnessToolCallDenied` events. When done, report to `yoke say --steering`, then release:

```text
yoke claims work release --item ITEM --reason "Dash completed"
```

## Laneless

```text
yoke direct-workflow dash evidence ITEM --result "<finding>" --verification "<observed proof>" --no-changes --json
```

Then transition to the terminal stage.
