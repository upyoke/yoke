# Usher — delivery

Merge-only stops here and keeps the claim at the delivery wait. Route A,
only for a flow that delivers nothing: re-enter the merge without
`--skip-status` to close the item out. Its envelope `status` reads `done`; a
`release_wait` block means the flow still owes delivery: use Route B.

```text
yoke merge item PREFIX-N --result "what shipped" --verification "<proof>"
```

Route B: a steering seat or reserving mandate means report and stop. Read
[delivery rules](../../../../.yoke/docs/agents/rules/delivery.md):

```text
yoke claims steering list --project PROJECT --active-only
yoke --env CONTROL_PLANE deployment-runs start-for-item PREFIX-N --project PROJECT --flow FLOW --environment ENVIRONMENT --json
yoke --env CONTROL_PLANE watch deploy -- RUN-ID
yoke merge item PREFIX-N --result "what shipped" --verification "RUN-ID, stages and QA"
```

Exit 2 waits for the operator's approval; never approve it yourself.
A preview lineage or preview claim with no registered mutation: stop as
`preview_lineage_mutation_unavailable`; escalate to the control-plane operator.
Exit 1 or 3: release `usher-halt-deploy-stage-failure` or
`usher-halt-deploy-infra-failure`. Next: [finalize](finalize.md).
