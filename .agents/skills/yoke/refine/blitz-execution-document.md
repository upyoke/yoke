# Refine — Blitz Execution Document

Lists: `next_offset` → `--offset`; keep filters.

## Select exactly one document
From `yoke strategy doc list`, use the explicit slug or the one matching
unarchived project document stating outcomes, slices, verification and
parent; else release and ask. Never create one. A different link blocks.
```bash
yoke strategy execution link "$ITEM_REF" --slug "$EXECUTION_SLUG" --project "$ITEM_PROJECT" --json
```
`strategy.execution.link` must read back through `yoke strategy execution get`
(`strategy.execution.get`) with `execution.execution_document.slug` equal to
the slug. After advancing, report
`Next step: /yoke {NEXT_SKILL_ID} {ITEM_REF}` and the slug.
