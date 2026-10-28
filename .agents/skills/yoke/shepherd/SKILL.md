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
Done when `yoke items detail get ITEM` shows the through-stage; read its
fresh `next_skill_id` and follow [shared handoff](../shared/stage-handoff.md).

If your launch instruction is a single-item mandate for this item, keep the
claim and run `/yoke {next_skill_id} ITEM` now: read and follow the next
bound skill in this turn. Otherwise show the next-skill line and release
the claim. A transition's `level_change` handoff takes precedence: release,
launch the returned successor, and end; follow `.yoke/docs/agents/levels.md`.
