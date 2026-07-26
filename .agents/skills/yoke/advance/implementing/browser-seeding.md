# Active — Browser Case Authoring

Browser verification is expressed by a plan attachment or an explicit
method-backed case. Do not infer and seed special requirement kinds from item
metadata.

## Reuse an attached plan

If the project already owns a plan whose Browser cases cover the item, attach
that plan at the intended transition:

```bash
yoke qa item-plan attach \
  --item "YOK-{N}" \
  --project "<project>" \
  --plan-id <plan-id> \
  --transition reviewing-implementation
```

The transition materializes one requirement per case. Do not duplicate those
requirements during implementation entry.

## Author an explicit Browser case

For genuinely one-off proof, add a method-backed requirement directly:

```bash
yoke qa requirement add \
  --item "YOK-{N}" \
  --method-id browser-check \
  --qa-phase verification \
  --instructions "<route and behavior to exercise>" \
  --expected-outcome "<observable passing outcome>" \
  --method-config '{"steps":[...]}'
```

Use `browser-check` when declared assertions can decide the result. Use
`browser-inspection` when screenshot evidence needs judgment. Method
configuration owns routes, waits, assertions, and captures; the instructions
and expected outcome explain the proof to reviewers.

If neither a reusable plan nor an explicit Browser case is required by the
item's verification contract, add nothing. The absence is explicit rather than
derived from a separate browser-testability field.
