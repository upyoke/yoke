# Architect — Hard Constraints

Reference content for the canonical architect prompt at `runtime/agents/architect.md`. Read this file before producing the technical plan, task specs, and worktree plan; the constraints below are part of every plan you write.

## Hard Constraints

1. **Session-fit sizing.** Every task must complete in one harness session without compacting.
   - XS: <10k tokens (config change, small doc edit)
   - S: 10-30k tokens (one component, straightforward)
   - M: 30-60k tokens (multiple files, moderate complexity)
   - L: 60-100k tokens (complex, many files — scrutinize carefully)
   - XL: >100k tokens — **NEVER ALLOWED. Must split further.**

2. **Worktree independence.** Tasks in different worktrees MUST NOT modify the same files. List every file each task touches. The overlap check will verify this programmatically.

3. **Logical dependency groups.** Files with logical dependencies (e.g., API contract types + route handlers, database schema + migration files) must be declared as dependency groups in the worktree plan. All files in a group must be assigned to the same worktree. The overlap checker enforces this.

4. **Sequential within, parallel across — default to fan-out.** Tasks within a worktree have a clear execution order; tasks across worktrees are fully independent. **Multi-worktree fan-out is the default for any epic where the File Budget admits it.** Conduct dispatches one Engineer subagent per active worktree in parallel, so two worktrees finish in roughly the time of the longer single worktree. Collapse to one worktree only when one of these structural blockers is present: (a) a genuine DAG where every task's output is read by the next task's input on a live shared surface (registry payload, seeded data, migration audit row); (b) every task touches the same hunk of the same file with semantically dependent edits no `coordination_only` edge can compatibly serialize; (c) the epic is <=3 tasks and worktree overhead exceeds the saved wall-clock. **Shared additive settings are NOT structural blockers** — claims can be split per worktree with disjoint file lists, and `coordination_only` edges handle additive same-file edits without serializing execution. The Worktree Plan's `## Worktree Decomposition` section names the chosen shape and justifies it against (a)/(b)/(c); a single-worktree choice on an epic with disjoint task groups must explicitly cite which blocker applies. See `runtime/agents/architect.md` § Worktree Decomposition for the full procedure.

5. **Tests, docs, and contracts are mandatory.** Every task specifies what tests to write, what docs to create/update, and its interface contracts.

6. **Epic-level acceptance criteria are mandatory.** The backlog item body must include an `### Acceptance Criteria` section (under `## Technical Plan`) with verifiable conditions derived from the item spec. Every spec requirement must map to at least one epic-level AC. Every epic-level AC must be covered by at least one task's ACs. These are checked at merge time — if a requirement exists only in prose but not in any AC, it will be missed. The `### FR Traceability` section (see Hard Constraint #7) provides the structural mapping that makes this verifiable.

7. **FR-to-task traceability is mandatory.** The `## Technical Plan` must include a `### FR Traceability` section (placed between `### Task Summary` and `### Task Dependency Graph`) containing a table that maps every FR-N identifier from the spec's `### Functional Requirements` section to the task number(s) that implement it. Before finalizing output, perform a self-check: enumerate every FR-N in the spec, verify each appears in the traceability matrix, and verify each mapped task's acceptance criteria cover the FR's intent. If any FR is unmapped, you MUST either create a task for it or provide a justified exclusion in the Coverage Note column (e.g., "Covered by existing code — verified by grep for `function_name`"). If the spec does not use FR-N notation (e.g., uses plain bullet lists), enumerate distinct requirements as R-1, R-2, etc. and produce the traceability mapping using those identifiers. Do NOT produce output with unmapped requirements.

8. **Epic size limit.** If an epic exceeds ~20 tasks, propose splitting into sequential epics and explain the split.

9. **Generated files.** Flag lock files, compiled output, and build artifacts as "auto-resolve on merge" in the worktree plan. Exclude them from overlap checks.

10. **Single-responsibility tasks.** Each task must have ONE primary concern. If a task description contains "AND" connecting different subsystems or concern types, split it. Combining distinct concerns (e.g., "write tests AND update docs") causes Engineers to complete one concern and overlook the other, resulting in expensive rework.

   **Split when you see:**
   - "Test X AND update documentation for Y" → separate test task + doc task
   - "Migrate A AND update B AND rewrite C" → one task per subsystem
   - "Implement feature AND write regression tests" → implementation task + test task (if the test suite is substantial)

   **Good decomposition (one concern per task):**
   - One task per script rewrite
   - One task per schema change
   - One task per test suite
   - One task per documentation update batch

   **Bad decomposition (multiple concerns in one task):**
   - "Migrate backlog registry AND update doctor checks AND rewrite rebuild-board" (three subsystems)
   - "Write regression tests AND update all documentation" (two distinct concern types)
   - "Implement API endpoint AND write E2E tests AND update README" (three concerns)

11. **Semantic anchors, not line numbers.** When referencing locations in existing code, use semantic anchors — function names, class names, section headers, variable names, comment markers, or unique string literals. **Never use line numbers** (e.g., "line 42", "lines 100-120", "L42"). Line numbers shift as earlier tasks in the same epic modify shared files, causing Engineers to edit the wrong location. Examples:
    - **Good:** "Add the new table creation after the existing `CREATE TABLE IF NOT EXISTS items` block in `create_core_tables()` (`runtime/api/domain/schema_init_tables.py`)"
    - **Good:** "Insert the new check below the `## Hard Constraints` section header"
    - **Good:** "Modify the items field projection logic in `handle_items_get()` (`runtime/api/domain/handlers/reads.py`)"
    - **Bad:** "Edit line 42 of `runtime/api/domain/schema_init_tables.py`"
    - **Bad:** "Insert after line 150"
    - **Bad:** "Modify lines 100-120 in `runtime/api/domain/handlers/reads.py`"

12. **Same-file sequencing.** After listing all files touched by all tasks, scan for files that appear in multiple tasks. When the same file is modified by multiple tasks within a worktree:
    - **Declare a dependency** between those tasks so they execute sequentially, not in parallel. The task that establishes the foundational structure must run first.
    - **Specify insertion anchors** in later tasks that reference content added by earlier tasks (e.g., "add after the `CREATE TABLE` block added by task 002").
    - **Flag it in the worktree plan** under a `## Same-file modifications` section listing which file, which tasks, and the required order.
    - **Real example of what goes wrong:** A module had 3 tasks all adding `CREATE TABLE` statements to `create_core_tables()` (`runtime/api/domain/schema_init_tables.py`). Without sequencing, each task's diff assumed a different baseline, producing cascading merge conflicts. With sequencing, task 2 builds on task 1's output and task 3 builds on task 2's.

13. **Live-state AC tagging.** Every AC that references live DB state, deployments, external services, or any shared mutable state MUST be tagged `[READ-ONLY]` or `[APPLY-MUTATION]`. No alternate spellings (`[MUTATE]`, `[WRITE]`). Untagged live-state ACs default to read-only interpretation by the Engineer, which means mutations will not happen unless explicitly tagged. See the Task Template's `## Acceptance Criteria` section for examples.

14. **Pack-first capabilities.** When a plan introduces a reusable capability (ops scripts, workflow definitions, deployment tooling, infrastructure patterns) for a specific project:
    - Check `packs/` for an existing focused Pack that owns the capability.
    - If none exists, include a task to create one versioned Pack bundle with explicit files, settings, dependencies, documentation, verification, and documented project gaps.
    - If one exists and the general capability has evolved, include a new Pack version and a preview-first project update task.
    - Installed Pack files go in the target project repo and become project-owned; runtime-generated files may go to scratch/deploy-run output.
    - Do not require project customizations to flow back into the Pack, and do not add drift policing, automatic pruning, or whole-project synchronization.
    - Project-specific config values go in DB settings/capabilities; project-visible policy/docs live in the managed project's `.yoke/` contract.
    - NEVER create project-specific scripts/configs in the Yoke repo as project-instantiated output.

15. **File size.** Every new tracked text file must land under 350 lines. The single rule and shared checker are owned by `runtime/api/domain/file_line_check.py`; pre-commit and advance/polish gates enforce it. Plan tasks with split files when designing modules near the limit.

16. **File Budget — upstream of the 350-line cap.** Constraint #15 is the late-stage backstop; this constraint is the upstream counterpart that planning is responsible for. Every implementation-bearing technical plan and every epic task spec that creates or grows authored code MUST preserve and elaborate the `## File Budget` contract authored at idea/refine time:
    - **Hard limit 350 lines per authored file**, **design target `<=300` lines** so implementors keep editing headroom.
    - Task specs MUST name the planned files/modules and a one-line single responsibility for each — vague language ("update relevant scripts") is a planning failure.
    - Worktree plans MUST NOT hand a single task an obvious oversized module responsibility. If a planned file is likely to exceed the design target, **split the responsibility across tasks or files BEFORE planning concludes**, not after the Engineer hits the wall mid-implementation.
    - When a touched source file is already at 300+ lines, name it explicitly in the plan and decide before implementation whether to split it first or keep additions tight enough to stay under the cap. Common collision points are large agent prompts (`runtime/agents/engineer.md`, `runtime/agents/tester.md`), large skill files, and shared domain modules.
    - The plan's File Budget reasoning is what Engineer dispatch and the implementation re-anchor consume — it must arrive at the implementor before the first new file is written.

## Documentation File Checklist

When creating a documentation task, review **every** file below and include any that references the changed capability. Don't just enumerate the obvious internal docs — check the top-level user-facing files too.

- `README.md` — project overview, feature descriptions, command reference, directory structure, FAQ
- `AGENTS.md` — project rules, file layout, command counts (the `CLAUDE.md` symlink points here)
- `.yoke/docs/commands.md` — command reference
- `.agents/skills/yoke/SKILL.md` — root command router
- Any other docs referenced in the project's `AGENTS.md` (e.g. an architecture overview or agent-patterns doc)

Missing even one file (especially README.md) means the feature is invisible to users who read that file. The Tester can only verify ACs that exist — if a doc file isn't listed, it won't be checked.
