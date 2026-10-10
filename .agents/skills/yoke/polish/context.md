# Polish — Gather Context

## 4. Gather Context

Read `spec`, `technical_plan` and `test_results` with
`yoke items get "$ITEM_REF" spec technical_plan test_results`. Use `body` only as fallback when spec is
absent; do not reread a whole rendered body alongside the same spec.
Identify every AC, scope boundary and relevant file/test.

## 5. Surrounding survey

Inspect the owning checkout's last 20 main commits and each registered lane:
```bash
git -C "$REPO_ROOT" log --oneline -20 main
git -C "<absolute-lane-path>" log --oneline main..HEAD
```

Check actual changes for signatures/APIs called by the branch, already-covered
scope and renamed/removed references. Flag adaptation or rebase needs before
fixing; preserve commits and follow governed lane preparation, never reset.

Use registered project-scoped item reads to survey active/pipeline work and
the last 15 done items:
```bash
yoke items list --project "$ITEM_PROJECT" --fields "id,title,status,workflow_id" --limit 1000
yoke items list --project "$ITEM_PROJECT" --status done --fields "id,title,status" --limit 15
yoke items dependency list "$ITEM_REF"
```

Use each item's actual pinned stages to identify pipeline work. For relevant
rows, read only needed scope/paths. Identify physical-file overlap, supersession,
merge order and directional dependencies. Claims coordinate ownership, never
narrow required scope. Resolve overlap through claims/dependency reconciliation;
another planned holder does not waive a current failure.

Carry **all** drift, overlap and recently shipped findings into
[review.md](review.md). Flag scope reduction only when landed work truly covers
the requirement; do not drop required files to avoid a claim.
