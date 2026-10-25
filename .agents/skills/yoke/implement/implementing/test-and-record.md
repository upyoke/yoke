# Tests and QA records

```text
yoke qa plan materialize --item PREFIX-N --transition <verification-stage>
yoke qa requirement list --item PREFIX-N --json
yoke qa plan run --item PREFIX-N --transition <verification-stage>
yoke qa case run --requirement-id <id>
```

The plan run is the one full execution; iterate with
`yoke watch pytest --impacted main --bounded`. Never run a case's command
by hand or substitute a smaller one.

- Exit 12: dispatch the returned review bundle now; submit its verdicts.
- `HUMAN_GATE`: checkpoint, route to steering or the owner, resume after.
- A `machine_qa.operator_gate` line with `self_approving: true` needs no
  action; never forward its code.
- Agent-verifiable requirements: commit, then record real evidence.
  Call `no_tests_declared` agent-attested, never tests run.

  ```text
  yoke qa run add --requirement-id <id> --performed-by agent --qa-kind ac_verification --verdict pass --raw-result "<evidence>"
  ```

- Outside-evidence pass: attach it with `yoke qa artifact add`.
- Migration modules: `yoke migration rehearse PREFIX-N` before review.
  Exception modules calling `record_audit_fingerprint`: run their CLI on
  validation and authoritative surfaces yourself before review.
