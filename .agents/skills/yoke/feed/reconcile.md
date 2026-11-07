# Feed — Reconcile Dependency Rows

Never touch non-Feed rows. `remove` deletes the whole pair: use it only
when every row is Feed's.

```text
yoke items dependency add PREFIX-N PREFIX-M feed --gate-point activation --satisfaction "status:done" --rationale "<why>"
```

Read back; record mismatches. Then finish:

```text
yoke events emit --name FeedCompleted --project <project> --kind lifecycle --type feed --source-type skill --severity STATUS --outcome completed
yoke claims work release --process FEED --project <project> --reason completed
```

Report exact refs: landings, item and edge changes, coherence, open
questions, and any `--no-new-items` suppression.
