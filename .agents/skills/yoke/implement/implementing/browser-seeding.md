# Active — Browser Case Authoring

Browser verification is expressed by a plan attachment or an explicit
method-backed case. Do not infer and seed special requirement kinds from item
metadata.

## Choose where the case runs

[Where a Browser case runs](../../../../../.yoke/docs/reference/browser-scenarios.md#where-a-browser-case-runs)
owns the phase, target, and transition for every Browser case, and names the
approval that replaces one when no server serves the change. Author the case
it selects.

## Reuse an attached plan

If the project already owns a plan whose Browser cases cover the item, attach
that plan at the transition the placement selects:

```bash
yoke qa item-plan attach \
  --item "PREFIX-{N}" \
  --project "<project>" \
  --plan-id <plan-id> \
  --transition reviewing-implementation
```

The transition materializes one requirement per case. Do not duplicate those
requirements during implementation entry.

## Author an explicit Browser case

For genuinely one-off proof, add a method-backed requirement directly. When
that section selects a pre-merge case against a candidate server:

```bash
yoke qa requirement add \
  --item "PREFIX-{N}" \
  --method-id browser-check \
  --qa-phase verification \
  --workflow-transition reviewed-implementation \
  --instructions "<route and behavior to exercise>" \
  --expected-outcome "<observable passing outcome>" \
  --method-config '{"steps":[{"action":"navigate","route":"/ROUTE"},{"action":"assert","target":"main","check":"visible"}]}'
```

When it selects a deployed environment, author the same case with
`--qa-phase post_deploy --target-env ENV` and bind `--workflow-transition` to
the pinned definition's release stage.

Use `browser-check` when declared assertions can decide the result. Use
`browser-inspection` when screenshot evidence needs judgment. Method
configuration owns routes, waits, assertions, and captures; the instructions
and expected outcome explain the proof to reviewers.

If neither a reusable plan nor an explicit Browser case is required by the
item's verification contract, add nothing. The absence is explicit rather than
derived from a separate browser-testability field.
