# Render the next stage handoff

After a successful transition, read the item again:

```text
yoke items detail get ITEM --json
```

Use `result.item.status` for the completed stage and
`result.item.workflow.next_skill_id` for `NEXT_SKILL_ID`. Render:

```text
Next bound skill: /yoke {NEXT_SKILL_ID} {ITEM}
```

When the field is empty, report that no next skill is bound. Never reuse the
entry read after a transition or select a skill from a workflow name or a
copied stage chain.

A refusal or artifact repair is not a forward handoff. Name the failed gate
and its concrete repair, then resolve the pinned binding at the current stage
before offering a skill re-entry. Do not route the operator to a named stage
skill whose binding does not own that stage.

`HC-skill-stage-handoffs` checks skill operator instructions and printed
handoffs. Descriptions, command catalogs, and same-skill re-entry are allowed.
An internal sub-skill invocation must explicitly call or dispatch the target
procedure by reading and following its `SKILL.md` in the current agent; that
instruction is exempt because it is not an operator handoff.
