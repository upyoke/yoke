# Release-time roles

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Agents](../index.md) > [Operation homes](index.md) > Release roles
<!-- /yoke:breadcrumbs -->

Member runs have two roles. Matrix:
`yoke deployment-runs --help`, `yoke qa plan run --help`, `yoke qa case run --help`,
`yoke merge item --help`. Model: [run members](../../deployments/model/run-members.md).

## The seat driving delivery owns the run

- Each run pins a source commit and a flow. Start it with
  `yoke --env CONTROL-PLANE watch deploy -- RUN-ID`.
- For a single run on a CI-gated flow, omit `--source-ref` to bind the gate branch tip: reuse the passed/running
  run on exactly that commit from any branch, dispatch only when it has none,
  or refuse failed/cancelled CI (`release_source_ci_failed`; fix the branch
  or rerun that commit's CI). `--source-ref` selects an explicit `release_lineage`.
- For a Stage/Production pair, resolve the full passing commit once. Create both runs
  with the same `--project-repo-path` and `--source-ref`; a moving branch tip can
  otherwise bind different commits. See the [pair recipe](#create-a-release-pair).
- Before creating a run, check member flows. Use their flow or reconcile explicitly; never
  change an item's flow silently.
- Creation enrolls carried ready items. `release_member_not_in_source`: merge the item
  and compose a new run. `add-item` attaches an item the candidate does not carry;
  `validate-composition` composes now and reports what it enrolled or skipped.
- Remove a wrong member with `yoke deployment-runs remove-item RUN-ID PREFIX-N --reason R`. After
  removing a member from a run failed at item QA, resume with
  `yoke watch deploy -- RUN-ID --from-stage item-qa`.
- Shared plans (at least two attaching members at item QA entry) and run QA belong only
  to this seat. Pending [plan groups](../../verification/deployment-plan-execution.md#plan-groups) and
  their failures are run-scoped notices to this seat: run each with
  `yoke qa plan run --deployment-run-id RUN-ID --stage item-qa --plan PLAN`, and on a
  failure triage the evidence and choose which attaching items owe a fix. Send only
  those items back with `yoke lifecycle transition PREFIX-N --from release --to
  implementing --reason R`; retry evidence failures with the same plan command,
  record an authorized waiver with `yoke qa requirement waive --requirement-id ID
  --rationale R --source operator --force`, or remove an item with the command above.
  The notice and fleet recovery name the pinned source commit: Retry uses that
  commit for environment/flaky failures only. A code fix needs a merge and a new
  run on a later commit, which takes over the newest earlier run when eligible. Waive discharges a case;
  remove detaches the member and leaves its delivery owed.
  Holders receive no shared-plan notices, whether pending, failed or passed.
- Workers whose own item has a QA finding that another item must fix first record it:
  `yoke items dependency add DEPENDENT BLOCKER operator --gate-point closure
  --satisfaction status:done --rationale R`.
- The driving seat never runs a member's item cases and never closes a member.
- Commits outside Yoke ship without an item; `yoke merge-receipt commits attest` is optional.

## Create a release pair

Resolve the intended commit once and verify its CI passed; use that full hash as
`PINNED_SHA` for both creates. `CHECKOUT` is the same absolute checkout path.
Respect any declared Stage or physical-QA gate before creating Production.

```sh
PINNED_SHA=$(git -C "$CHECKOUT" rev-parse HEAD)
yoke --env CONTROL_PLANE deployment-runs create PROJECT STAGE_FLOW --environment stage --project-repo-path "$CHECKOUT" --source-ref "$PINNED_SHA" --idempotency-key STAGE_KEY
yoke --env CONTROL_PLANE deployment-runs create PROJECT PROD_FLOW --environment prod --project-repo-path "$CHECKOUT" --source-ref "$PINNED_SHA" --idempotency-key PROD_KEY
```

If a correction lands, resolve its passing commit and create a new pair; earlier
Stage proof does not cover it.

## The member owner owns its item

- Run the member's item cases with
  `yoke qa plan run --item PREFIX-N --stage STAGE`. Dropping `--stage`
  or another item does not answer that obligation. A post-deploy plan attached by
  exactly one member at item QA entry runs here as that member's QA; its holder wakes
  and runs it. Shared-plan-only holders park until close-out. Ownership stays fixed
  when another member attaches later. `yoke qa case run` never
  credits a stage.
- A refused automatic close-out wakes you with its blockers; read
  `yoke qa gate-summary --item PREFIX-N --target implemented`. It retries when they settle.
- An operator-wake surface (a desktop app) is re-entered by that operator or a steering seat,
  never by Yoke.
- `yoke merge item` is the one close-out, at merge and at the release wait, with `--result` and
  `--verification`.
- After a takeover, continue your execution ID
  ([run members](../../deployments/model/run-members.md)).

## Related

- [Deployment runs and packaged capabilities](delivery.md)
- [Pack capabilities](packs.md)
