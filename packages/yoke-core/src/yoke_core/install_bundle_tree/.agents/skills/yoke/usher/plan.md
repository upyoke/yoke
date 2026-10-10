# Usher — plan

Explicitly named items already authorize execution; no repeat confirmation.
After collect passes, normal mode continues to [merge](merge.md);
deploy-only/resume continues to [deploy](deploy.md).

Dry-run is read-only and stops here. Read each item's projected flow value
and project, group by project+flow, then resolve actual target and approvals:

```text
yoke items get PREFIX-N deployment_flow project --json
yoke deployment-runs resolve-target PROJECT FLOW
yoke deployment-flows stages FLOW --json
```

The flow is result.fields.deployment_flow.value; human "flow (source)" is
not an ID. Successful empty target is merge-only; unavailable/unresolved
target cannot be guessed merge-only. Use collect's dependency rows once
to show hard-block edges, merge order, rationale and inspection command.

Print item count/order, dependency edges or none, routing and expected
approval stages. Route A names verified no-delivery flow and
watcher done-transition --skip-deploy. Route B lists project, registered
flow, environment/tier and grouped members. Name unresolved policy/refusals.
Print "Dry run complete" and stop without acquiring work claims,
transitions, merges, runs or deployment execution.
