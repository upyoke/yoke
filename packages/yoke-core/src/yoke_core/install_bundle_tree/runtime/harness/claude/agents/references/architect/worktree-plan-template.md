## Worktree Plan Template

Copy exact downstream headings. Plan includes:
- `## Worktree Decomposition`: each lane/tasks/budget root, single-lane structural
  blocker (DAG/same-hunk/tiny-epic), foundation→consumer activation dependencies.
- Per lane `## Worktree: PREFIX-{N}[-{worktree-suffix}]`, matching `Branch:`,
  `Tasks: #NNN, #NNN`, `Files touched:` with file/action/task ownership.
- `Generated files (auto-resolve on merge):`
- `## Dependency groups`: intra/inter-lane.
- `## Same-file modifications`
- `## File overlap check`: intra/cross-lane.
- `## Execution order`: within-lane plus cross-lane activation gates.
- Optional `## Cross-Task Merge Plan` only for sibling code needed before Engineer
  dispatch: predecessor branches and per-task merge order, reviewed-implementation+
  predecessors. Conduct S6f consumes it; exact example is in
  `.agents/skills/yoke/conduct/entry-activation-resolution.md` S6f step4a.

Every shared-path pair gets decision-build evaluation before final output:
coordination_only for attested independence, directional activation when ordered,
Plan Caveats when ambiguous. Cross-lane overlaps lacking independent coordination
require re-partition/merged groups and revised structural justification.
