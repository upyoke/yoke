# Release-time roles

<!-- yoke:breadcrumbs -->
[Yoke](../../index.md) > [Agents](../index.md) > [Operation homes](index.md) > Release roles
<!-- /yoke:breadcrumbs -->

A run with members has two roles. Each `--help` carries the matrix:
`yoke deployment-runs --help`, `yoke qa plan run --help`, `yoke qa case run --help`,
`yoke merge item --help`. Model: [run members](../../deployments/model/run-members.md).

## The seat driving delivery owns the run

- Pin one source commit. Create the stage and production runs from it and start each with
  `yoke --env CONTROL-PLANE watch deploy -- RUN-ID`.
- On CI-gated flows, omit `--source-ref` to bind the gate branch tip: reuse the passed/running
  run on exactly that commit from any branch, dispatch only when it has none,
  or refuse failed/cancelled CI (`release_source_ci_failed`; fix the branch
  or rerun that commit's CI). Give stage that `release_lineage` via `--source-ref`.
- Before a pair, check the members' completion flows. Use a run of that flow or
  reconcile item flows; never change an item's flow silently.
- Creation enrolls carried delivery-ready items. `release_member_not_in_source`: merge the item
  and compose a new run. `add-item` attaches an item the candidate does not carry;
  `validate-composition` composes now and reports what it enrolled or skipped.
- Remove a wrong member with `yoke deployment-runs remove-item RUN-ID PREFIX-N --reason R`. After
  removing a member from a run failed at item QA, resume with
  `yoke watch deploy -- RUN-ID --from-stage item-qa`.
- Workers who find item QA blocked by another item record it:
  `yoke items dependency add DEPENDENT BLOCKER operator --gate-point closure
  --satisfaction status:done --rationale R`.
- The driving seat never runs a member's item QA and never closes a member.
- Commits outside Yoke ship without an item; `yoke merge-receipt commits attest` is optional.

## The member owner owns its item

- Run the member's stage QA with
  `yoke qa plan run --item PREFIX-N --stage STAGE`. Dropping `--stage`
  or another item does not answer that obligation. `yoke qa case run` never
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
