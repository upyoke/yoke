# Feed — gather (read-only)

## Scope and strategy authority

Default: non-terminal, non-frozen frontier. Explicit `_scope_ids`: deep-read/
report those targets, fail clearly for missing refs, and inspect surrounding
graph context. Expand mutation scope only when a shared-surface blocker forces it.

Read full strategy once unless `_no_new_items` AND truly graph-refresh-only:

```sh
yoke strategy doc get MISSION
yoke strategy doc get LANDSCAPE
yoke strategy doc get VISION
yoke strategy doc get MASTER-PLAN
yoke items list --project <project> --frozen 0 --fields "id,title,status,workflow_id,workflow_version_id,priority"
```

Retain strategic anchors, constraints, near-term priorities and MASTER-PLAN's
current completion/next natural boundary. Identify already materialized work
and gaps from this DB content, rather than re-reading its rendered file.
Filter frontier terminal statuses (`done`, `cancelled`, `stopped`, `failed`);
derive explicit targets or the whole frontier.

## Target artifacts and graph

Use each target's content index/structured fields; record empties, readiness,
unmeasurable assumptions, status counts and overlaps. Read relevant fields once:
`yoke items get PREFIX-N spec`,
`yoke items get PREFIX-N design_spec`,
`yoke items get PREFIX-N technical_plan`.
Generated task graphs additionally use
`yoke items get PREFIX-N worktree_plan` and
`yoke items get PREFIX-N shepherd_caveats`.
Use `yoke items get PREFIX-N body` only as an alternative when needed for
rendered narrative; avoid duplicating its structured content.
Resolve generated-children posture through `workflows.item.get`.

```sh
yoke items dependency list PREFIX-N
```

Record both directions, blocker/dependent identities, activation/integration/
closure gates and source attribution (Feed vs manual operator/Idea/Shepherd).
Terminal/cancelled blockers are staleness candidates, not automatic removals.

## Recent landed impact — required

```sh
git log --oneline -30
git log --oneline --since="3 days ago"
git diff <commit>~1..<commit> --stat
```

Inspect relevant landed commits' actual files/schema/contracts/prompts/hooks/
docs/tests/scripts, record stable item/commit identities, and assess every
target's affected fields/assumptions. Produce the concrete list:
“These work items need updating because X landed and changed Y.”

Inspect likely shared physical paths/contracts/generated flows/test harness/
deployment surfaces for real coding/merge hot spots. Carry forward target
artifacts, existing graph, full needed SML, recent changes, actionable updates
and materialization gaps; keep these facts current instead of repeating dumps.
