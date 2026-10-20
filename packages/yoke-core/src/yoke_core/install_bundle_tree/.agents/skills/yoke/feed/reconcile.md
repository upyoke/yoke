# Feed — Reconcile Dependency Rows

Never touch non-Feed rows. `remove` deletes the whole pair: use it only
when every row is Feed's.

```text
yoke items dependency add PREFIX-N PREFIX-M feed --gate-point activation --satisfaction "status:done" --rationale "<why>"
```

Read back; record mismatches. Next: [summarize.md](summarize.md).
