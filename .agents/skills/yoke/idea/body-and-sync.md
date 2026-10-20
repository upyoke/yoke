# Idea — Persist, Verify, Close

## 8. Spec

Behavior, verified references, `- [ ] AC-N:` ACs, and a
[File Budget](file-budget.md) when enabled. Then
[db-claim-classification.md](db-claim-classification.md).

```text
yoke items structured-field replace "$ITEM_REF" --field spec --source idea --stdin < <spec-file>
yoke claims path register --item "$ITEM_REF" --paths <every-required-path> --allow-planned
```

Register only when path claims are on; `required_per_task` registers per
task later. Overlap: [path-claim-blocking.md](path-claim-blocking.md).

## 10. Readiness and release

```text
yoke items github-sync "$ITEM_REF"
yoke readiness check "$ITEM_REF" --json
yoke claims work release --item "$ITEM_REF" --reason idea-complete
```

Release only on `verdict` pass, after [path-closure.md](path-closure.md).
Otherwise keep the claim and show the fix.
