# Idea / Dash — Delivery Evidence Intake

Only for requested screenshots, environment QA or approval. Placement:
[browser targets](../../../../.yoke/docs/verification/browser-targets.md#where-a-browser-case-runs).
Never edit a shared flow; assign an item-only one instead.

```text
yoke qa requirement add --item PREFIX-N --method-id browser-inspection --qa-phase post_deploy --target-env ENV --requirement-source explicit --instructions "<capture>" --expected-outcome "<shows>" --workflow-transition release
```

A screenshot does **not** add approval. "Have me approve it" needs
`required_human` on the item-scoped QA stage, operator in `actors`,
`mode=all`. Use `human_if_unsure` only for explicitly conditional approval.
