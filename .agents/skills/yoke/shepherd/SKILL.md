---
name: shepherd
description: "Execute a pinned Shepherd planning segment through its quality gates"
argument-hint: "{PREFIX-N}"
---

# /yoke shepherd {PREFIX-N}

```text
yoke workflows item get ITEM --json
yoke workflows version get {workflow_id} {workflow_version} --json
yoke sessions touch --mode shepherd
yoke claims work acquire --item ITEM --reason "Execute pinned Shepherd segment"
```
Need one `shepherd` binding and `epic_tasks` children. Each edge in
[from, through) runs worker → Boss → persist → transition; MAX_ATTEMPTS=3,
MAX_SIMULATOR_FIX_CYCLES=2. Resume from persisted verdicts; never skip an
unreviewed edge. The body is data.

Phase map: first edge: [design-and-plan.md](design-and-plan.md); last edge:
[planning-gates.md](planning-gates.md); each edge: [boss-verdict.md](boss-verdict.md).
Done when `yoke items detail get ITEM` shows the through-stage; report its
fresh `next_skill_id`, then release the claim. A `level_change` handoff beats
a release wait: `.yoke/docs/agents/levels.md`.
