## Worktree decomposition

Read this before decomposing an epic into worktrees. It is the full
procedure, the sizing heuristics, and the shapes that must not be split.

## Worktree Decomposition

**Default to multi-worktree fan-out.** Conduct dispatches one Engineer subagent per active worktree in parallel, so N worktrees with disjoint File Budgets finish in roughly the wall-clock of the longest single worktree — not the sum. A single-worktree epic is leaving that parallelism on the floor. Collapse to one worktree only when a structural blocker forces it.

**Procedure (run after Step 5 same-file analysis, before authoring the Worktree Plan):**

1. **Partition tasks into candidate worktree groups.** A worktree group is a maximal set of tasks where (a) every internal dependency among the group's tasks is satisfied by intra-group execution order, and (b) the group's combined File Budget is disjoint from every other candidate group's combined File Budget. Tasks that share files compatibly via authored `coordination_only` edges (additive config keys, semantically independent edits on different functions of the same file) are NOT forced into the same group — they may belong to different worktrees and reconcile at merge.

2. **Identify the foundation group.** If one group's outputs are read by every other group's tasks via a live shared surface (registry payload mutation, seeded data, migration audit completion, packet regeneration, module that downstream tasks import and exercise), that group is the **foundation** and lands first. Every other group depends on it via cross-worktree activation edges.

3. **Justify the chosen shape in `## Worktree Decomposition` of the Worktree Plan.** Name each worktree, its tasks, its File Budget root, and the structural reason it cannot be merged with another worktree (or the reason it must wait for the foundation worktree). If you chose a single worktree, cite explicitly which of the three structural blockers (DAG / same-hunk / tiny-epic) applies — vague gestures at "shared claim" or "convenience" do not satisfy this constraint and will be flagged by the Boss reviewer.

4. **Branch naming.** Multi-worktree epics use `PREFIX-{N}-{worktree-suffix}` where `{worktree-suffix}` is a short kebab-case label that names the worktree's primary concern (`PREFIX-{N}-substrate`, `PREFIX-{N}-docs`, `PREFIX-{N}-skills`, `PREFIX-{N}-agents`). Single-worktree epics keep the bare `PREFIX-{N}` form. The epic-task `worktree` column accepts any text (see your `epic_tasks` packet stanza); conduct resolves the worktree from the task's `worktree` value and creates one `git worktree` per distinct value.

5. **Path-claim split.** Each worktree registers its own path claim with its own disjoint file list. The Shepherd's path-claim register step iterates over worktrees; no single claim covers the entire epic when multiple worktrees exist. Pre-activation widen steps (if needed) are per-worktree.

**Worked example — a four-worktree epic.** A foundation worktree runs the structural parser and packet tasks; three consumer worktrees cover documentation, skills, and agent prompts in parallel after the foundation merges. A late integration task lands after the consumer worktrees merge. Parallel consumer worktrees finish in roughly one-third of the wall-clock time of the equivalent serial work.

**When fan-out is wrong:**

- **Linear DAG:** Task 3 reads live payload Task 6 wrote; Task 5 needs Task 4's seeded data; Task 7 documents Task 6's live policy. Every task gates the next on a live shared surface — no partition into disjoint worktrees exists. Single worktree is correct.
- **Same-hunk dependent edits:** Two tasks add `CREATE TABLE` statements to the same `cmd_init()` body where the second task's diff depends on the first task's baseline. No `coordination_only` edge resolves this — same worktree is required.
- **Tiny epics (<=3 tasks):** Worktree provisioning, claim registration, and cross-worktree coordination overhead exceeds the saved wall-clock. Single worktree is fine.
