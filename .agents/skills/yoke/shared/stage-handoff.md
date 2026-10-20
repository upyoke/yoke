# Next stage handoff

After a successful transition, read the item again; never reuse the earlier read:

```text
yoke items detail get ITEM --json
```

Render `Next bound skill: /yoke {result.item.workflow.next_skill_id} {ITEM}`, or say none is bound. After a refusal, name the failed gate and its repair instead; offer only the skill bound to the current stage.
