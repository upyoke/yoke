# Idea — DB Classification

Read the spec and classify the actual governed DB work. Projects without a
`migration_model` capability need no governed mutation claim.

- Real governed mutation: amend the full claim (apply modules need the
  [history AC](body-and-sync-functions.md)), or add
  `## DB Claim Blocker (idea-time)` and do not call `db-claim amend`.
- No governed mutation, including governance discussion: record a reviewed-none
  decision with the reason the work does not mutate the governed database.

```text
yoke db-claim amend "$ITEM_REF" --reason "<reason>" --state none
```

New workflow versions check lane-only numbered migration files against the
integration target, not spec wording. New entries need a declared claim even
with a reviewed-none stamp. Review entry and merge preflight enforce this.
Older pins retain the prose gate; boot moves eligible open canon pins after
workflow convergence and leaves edited or incompatible pins for explicit
`yoke workflows item migrate` recovery.
