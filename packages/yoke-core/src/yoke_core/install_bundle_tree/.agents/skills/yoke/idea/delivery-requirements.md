# Idea / Dash — Delivery Evidence Intake

Only for requested screenshots, environment QA or approval. Placement:
[browser targets](../../../../.yoke/docs/verification/browser-targets.md#where-a-browser-case-runs).
Never edit a shared flow; assign an item-only one instead. Intake only
persists: never run QA or create deployment runs.

```text
yoke qa requirement add --item PREFIX-N --method-id browser-inspection --qa-phase post_deploy --target-env ENV --requirement-source explicit --instructions "<capture>" --expected-outcome "<shows>" --workflow-transition release
yoke items scalar update PREFIX-N --field deployment_flow --value <flow-id>
```

Set `--workflow-transition` to the stage owning that phase; never bind
`post_deploy` to review. Dash items first run
`yoke workflows item-posture amend PREFIX-N --verification-method browser-inspection --reason "<request>"`.

A screenshot does **not** add approval. "Have me approve it" needs
`required_human` on the item-scoped QA stage, operator in `actors`,
`mode=all`. Read that stage's target kind (`persistent_environment` or
`run_preview`); never assume one. Use `human_if_unsure` only for explicitly conditional approval.
