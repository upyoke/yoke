# Dash — verify

Commit and survey touched files before each case; any tree change reruns it.

```text
yoke qa item-plan attach --item ITEM --project P --plan-id <id> --transition reviewing-implementation --qa-phase verification
yoke qa plan materialize --item ITEM --transition NEXT_STAGE --json
yoke qa case run --requirement-id <requirement-id>
```

A capture is not a pass. Owed post-deploy QA: attach a release-stage plan or record none. Then transition.

```text
yoke qa post-deploy record-no-obligation --item ITEM --reason "<why no observable obligation>"
```

Next: [merge](merge.md).
