# Deployment runs and capabilities

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Agents](../index.md) > [Operation homes](index.md) > Delivery
<!-- /yoke:breadcrumbs -->

Model: [delivery](../../deployments/index.md); occupancy, takeover and drivers:
[run members](../../deployments/model/run-members.md#target-occupancy-serializes-deploys-no-claim-is-taken).

## Deployment runs

- Merge before release; the hosted flow owns the commits and proof. Remote changes start
  from a local commit.
- Run creation and driving take no claim. `/yoke usher PREFIX-N` uses
  `yoke deployment-runs start-for-item`; drive with `yoke watch deploy -- RUN_ID`.
- A run occupies its target servers until its QA settles. `target_occupied` names the holder:
  wait for it or follow its recovery. A run with a live driver answers only to that session.
- `run_busy` retries, never fails. Resume stopped drivers:
  `yoke watch deploy -- RUN_ID`. Never duplicate a run.
- A newer run on the same flow and target takes over a run waiting only on item QA. Live
  member QA moves intact ([run members](../../deployments/model/run-members.md)). While a
  steering seat covers the project, only the seat holder or the older run's creator may. Others
  report and wait: `printf %s "LANDED <ref> <merge sha>" | yoke say --stdin --steering`.
- A self-deploy needs this machine's paired same-universe DB connection; otherwise escalate the
  named refusal. Never look for control-plane database credentials to deploy.
- Retire a flow with `yoke deployment-flows set-status FLOW disabled`; change one with
  `yoke deployment-flows version`. Never delete a flow a run references.
- Before retrying or failing a start with a lost response, read
  [start diagnostics](../../deployments/start-diagnostics.md).

## Binding-based multi-project delivery

- A stage's `input_bindings` ships another project's branch; read pins with
  `yoke deployment-runs get RUN-ID bound_sources`. One commit per project per run.
- A release that writes its own commit (a version-pin promotion) records it with
  `yoke deployment-runs release-output record RUN-ID --project P`.
- A consumed bound source whose branch moved needs a new run. A stale carried-work record or
  `candidate_containment_attestation_stale` names its recovery; follow it.
- A carried item with no completion flow: `yoke workflows delivery-default set --project P
  --workflow W --flow F`, then retry the start.

## QA across release targets

A case selects its registered environments with `target_envs`. A case that needs
real traffic sets `wake_path: manual` with
`wake_evidence`
([real traffic](../../verification/standalone-plans.md#cases-that-wait-for-real-traffic)).
Records stay on this control plane.

## Wait on another item's merge or delivery

Record the wait, then park. Use the item skill, not `dash`, or `operator` for steering:

```text
yoke items dependency list ITEM
yoke items dependency add ITEM BLOCKER dash --gate-point integration \
  --satisfaction fact:merged --rationale "needs blocker merged"
yoke sessions touch --mode parked --reason "awaiting BLOCKER merge"
```

- Add the edge before the landing you need: an unfinished blocker's landing counts only after the
  edge exists. A blocker at `done` always satisfies it. Re-add an older edge to re-land.
- Record a delivery wait only when a QA finding is in your own item and another item must
  land first. Use `--gate-point closure`: `fact:merged` if the fix ships in the same
  release, `fact:deployed:prod` only if it must be live first.
- Park only after the write succeeds. On `dependency_cycle`, settle it with steering, or use
  `coordination_only` when independent. Keep the claim and lane.
- Your own item's release wait needs no edge. Details: `yoke items dependency add --help` and
  [dependencies](../../items/model/dependencies.md).

## Related

- [Release-time roles](release-roles.md)
- [Pack capabilities](packs.md)
