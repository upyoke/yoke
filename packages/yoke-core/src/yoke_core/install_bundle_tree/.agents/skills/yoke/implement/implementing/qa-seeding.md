# QA seeding

Attached plans supply cases. Add a requirement only for missing coverage,
at the pinned QA stage; never seed free-form smoke or e2e requirements.

```text
yoke qa requirement add --item PREFIX-N --qa-kind ac_verification --qa-phase verification --workflow-transition reviewed-implementation --requirement-source ac_derived --success-policy all-pass
```

Browser proof, only when the item requires it:
[placement](../../../../../.yoke/docs/verification/browser-targets.md#where-a-browser-case-runs)
picks the stage. Attach a covering plan, else add a `browser-check` case.
Before a capture, wait for a settled page: no loading text and no covering
overlay.

```text
yoke qa item-plan attach --item PREFIX-N --project P --plan-id <plan-id> --transition <stage>
```
