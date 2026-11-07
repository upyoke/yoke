# Idea — DB Classification

Read the spec and classify the actual governed DB work. Projects without a
`migration_model` capability need no governed mutation claim.

- Real governed mutation: amend the full claim, or add
  `## DB Claim Blocker (idea-time)` and do not call `db-claim amend`.
- No governed mutation, including a schema-only additive change or governance
  discussion: record a reviewed-none decision with the reason no governed migration is needed.

A claim that applies modules needs this AC, naming each module:
`- [ ] AC-N: Each declared migration entry remains permanent ordered history,
safe to re-run and never deleted after apply.`

```text
yoke db-claim amend "$ITEM_REF" --reason "<reason>" --state none
```

New workflow versions check lane-only numbered migration files against the
integration target, not spec wording. New entries need a declared claim even
with a reviewed-none stamp. Review entry and merge preflight enforce this.
Older pins retain the prose gate; boot moves eligible open canon pins after
workflow convergence and leaves edited or incompatible pins for explicit
`yoke workflows item migrate` recovery.
