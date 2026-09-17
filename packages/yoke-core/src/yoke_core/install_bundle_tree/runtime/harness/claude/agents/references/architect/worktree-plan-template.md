## Worktree plan template

The exact template for the worktree plan you write. Copy its shape; every
heading it names is read by a downstream consumer.

## Worktree Plan Template

Every worktree plan must include:
- `## Worktree Decomposition` — names every worktree, its tasks, its file-budget root, the structural-blocker justification (DAG / same-hunk / tiny-epic) for any merged worktrees, and the cross-worktree activation edges connecting foundation -> consumer worktrees. A single-worktree epic still includes this section and cites the blocker.
- For each worktree:
  - `## Worktree: PREFIX-{N}[-{worktree-suffix}]`
  - `Branch: PREFIX-{N}[-{worktree-suffix}]`
  - `Tasks: #NNN, #NNN`
  - `Files touched:` with file/action/task ownership (worktree-scoped)
- `Generated files (auto-resolve on merge):`
- `## Dependency groups` (intra-worktree and inter-worktree)
- `## Same-file modifications`
- `## File overlap check` (intra-worktree AND cross-worktree — cross-worktree overlaps are a planning error and force re-partition)
- `## Execution order` (per worktree, plus cross-worktree activation gates)
- `## Cross-Task Merge Plan` (OPTIONAL — include when a task's branch needs sibling-task code merged in before Engineer dispatch; omit otherwise) — per-task entries naming predecessor branches and dispatch-time merge order. Conduct S6f reads this section and executes the listed merges; predecessors must be `reviewed-implementation`+. Format example lives in conduct's [entry-activation-resolution.md](../../.agents/skills/yoke/conduct/entry-activation-resolution.md) S6f step 4a.

Any task pair surfaced by `## File overlap check` (i.e., sharing at least one File Budget path) MUST also be evaluated by `### Step 5.5` above before the plan is finalized — the worktree-plan view names the overlap, and Step 5.5 turns each overlap into either a `coordination_only` edge, an `activation` edge with `fact:merged`, or a `## Plan Caveats` bullet. Cross-worktree overlaps that cannot be resolved as `coordination_only` are a partition error: re-merge the affected groups into one worktree and re-justify.
