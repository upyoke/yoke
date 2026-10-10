# Shepherd — final handoff gates

Before through-stage: flow is hard; remaining checks advisory.
PRD validation enforces AC presence upstream; Boss checks defensively.

**Flow:** registered items.get.run deployment_flow JSON yields {value,source},
item pin else project default. Plain "flow (source)" is not an ID.

```text
yoke items get ITEM deployment_flow --json
```

Unreadable source stops by name. Empty value blocks: show registered flows for
the item's project and obtain an authorized selection. Never invent a route.

**Pack reuse:** for a project consuming Packs, spec stance must be project-owned
with Reason, or pack-update with Pack scope. Ask whether another consumer would
want the change on update. Publishing belongs to owning project; consumer apply
needs the mandatory linked companion item. Missing stance/support is advisory.

**ACs:** flag vague, unmeasurable or combined checks; propose independent testable
rewrites. **Overlap:** bounded registered inventory of planned/inflight work,
excluding self, idea and terminal states; advise on subsystem/scope/files and
confirm split before execution. **Task independence:** inspect persisted tasks
for extensive same-file edits, uncontracted output consumption and implicit
cycles; suggest explicit contracts/restructuring. Advisory is never a gate waiver.
