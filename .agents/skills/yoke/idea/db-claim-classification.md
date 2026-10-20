# Idea — DB Classification

Pipe the non-empty spec in; a failed read stops here.

```text
yoke items get "$ITEM_REF" spec
yoke db-claim prose-check --stdin --public-ref "$ITEM_REF" --json
```

- No triggers: `--state none`, reason
  `idea: spec/body declares no governed DB mutation`.
- Real mutation: amend the full claim (apply modules need the
  [history AC](body-and-sync-functions.md)), or add
  `## DB Claim Blocker (idea-time)` and do NOT call `db-claim-amend`.
- DB governance talk only: `--state none`, reason
  `idea: work item discusses DB governance vocabulary but performs no governed DB mutation; reviewed-none`.

```text
yoke db-claim amend "$ITEM_REF" --reason "<reason>" --state none
```
