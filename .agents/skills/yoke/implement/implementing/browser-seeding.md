# Browser cases

Only when the item requires Browser proof.
Before a browser capture, wait for a settled page: no loading text and no covering overlay.
[Placement](../../../../../.yoke/docs/verification/browser-targets.md#where-a-browser-case-runs)
picks the stage. Attach a covering plan, else add a `browser-check` case:

```text
yoke qa item-plan attach --item PREFIX-N --project P --plan-id <plan-id> --transition <stage>
```
