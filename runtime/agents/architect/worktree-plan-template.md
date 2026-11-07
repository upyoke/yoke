## Worktree Plan Template

Use these headings exactly:

- `## Worktree Decomposition`: each lane, its tasks and budget roots, the
  structural reason for any single lane, and foundation→consumer activation
  dependencies.
- Per lane, `## Worktree: PREFIX-{N}[-{worktree-suffix}]` with a matching
  `Branch:`, `Tasks: #NNN, #NNN`, and `Files touched:` giving each file's
  action and owning task.
- `Generated files (auto-resolve on merge):`
- `## Dependency groups`: within and across lanes.
- `## Same-file modifications`
- `## File overlap check`: within and across lanes.
- `## Execution order`: within each lane and across lanes. Every order here is
  also a task dependency; Conduct dispatches by dependencies and reads no prose.
- `## Cross-Task Merge Plan`, only when a task needs sibling code before its
  Engineer starts: predecessor branches and merge order. Each predecessor is
  also a dependency of the consuming task
  (`.agents/skills/yoke/conduct/entry-activation-resolution.md`).
