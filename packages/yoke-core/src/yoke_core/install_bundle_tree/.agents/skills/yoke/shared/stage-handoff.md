# Next stage handoff

After a successful transition, read the item again; never reuse the earlier read:

```text
yoke items detail get ITEM --json
```

Render `Next bound skill: /yoke {result.item.workflow.next_skill_id} {ITEM}`, or say none is bound. After a refusal, name the failed gate and its repair instead; offer only the skill bound to the current stage.

If your launch instruction is a single-item mandate for this item, keep the
claim and run `/yoke {next_skill_id} ITEM` now: read and follow the next
bound skill in this turn. Otherwise show the next-skill line and release
the claim. A transition's `level_change` handoff takes precedence: release,
launch the returned successor, and end; follow `.yoke/docs/agents/levels.md`.
