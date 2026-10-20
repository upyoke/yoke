# Refine — Pinned Context

`ITEM_REF` is the public PREFIX-N.
```bash
yoke workflows item get "$ITEM_REF" --json
yoke workflows version get "$ITEM_WORKFLOW_ID" "$ITEM_WORKFLOW_VERSION" --json
```
Find the one `refine` binding whose range [from, through) holds the status
with one stage after `from`; else stop. Source = from, active = next,
target = through. Scope is `generated_task_plan` if generated_children is
`epic_tasks` and a `shepherd` binding ends at `from`, else `item_artifact`.
ITEM_NEXT_SKILL is the skill of the binding whose range holds target.
