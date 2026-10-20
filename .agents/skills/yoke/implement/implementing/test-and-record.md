# Tests and QA records

```text
yoke qa plan run --item PREFIX-N --transition <verification-stage>
yoke qa case run --requirement-id <id>
```

The plan run is the one full execution; iterate with
`yoke watch pytest --impacted main --bounded`. Never run a case's command
by hand or substitute a smaller one.

- Exit 12: dispatch the returned review bundle now; submit its verdicts.
- `HUMAN_GATE`: checkpoint, route to steering or the owner, resume after.
- Commit before `yoke qa run add`. Call `no_tests_declared` agent-attested.
- Migration modules: `yoke migration rehearse PREFIX-N` before review.
  Exception modules calling `record_audit_fingerprint`: run their CLI on
  validation and authoritative surfaces yourself before review.
