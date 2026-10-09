# Simulate Phase: Canonical Simulator Dispatch Prompts

Dispatch the read-only `yoke-simulator` with the common contract below and exactly one mode prompt. Include both in the actual dispatch.

## Common contract — append to every mode prompt

For each modified write path, trace external-call failures, safe propagation under `set -e`, compatibility with the previous error model, and failure-case test coverage. Report gaps with `[CRITICAL]`, `[WARNING]`, `[NOTE]`; name verified paths, mismatch/root cause, affected tasks, concrete fix guidance and `Fix level: plan|code|mixed`.


## Plan Simulation Prompt

```text
Simulate the plan for epic "{epic-ref}".
Item ID: {public_ref}

## Phase: PLAN (pre-sync, pre-implementation)

Trace the planned architecture for integration gaps. No code has been written yet — you are checking the plan's structural soundness.

Begin with SIMULATION: CLEAN or SIMULATION: GAPS FOUND, then EPIC: {public_ref}. Wrong epic refuses exit 16; missing EPIC refuses exit 17.

Read the authoritative item spec and plans from the DB:
yoke items get {public_ref} spec
yoke items get {public_ref} technical_plan
yoke items get {public_ref} worktree_plan

## Task Content
{for each task: task number, title, and body content from yoke workflow-item epic-task body-get}

## Context Budget Guidance
Use inline task bodies; read authoritative parent spec/plans without fetching those bodies again.

## Instructions
Focus on:
- Interface contract mismatches between dependent tasks
- Worktree visibility assumptions
- Dependency ordering feasibility
- Environment and runtime assumptions that vary across tasks
- Merge sequence predictions

Apply the common contract and return your gap report.
```

## Standard Integration Prompt

```text
Simulate the integration for epic "{epic-ref}".
Item ID: {public_ref}

## Phase: INTEGRATION (post-execution, pre-merge)

All tasks are complete (or: the following tasks are incomplete and should be excluded from path tracing: {list}). Trace actual code across worktrees for integration gaps before merging.

Begin with SIMULATION: CLEAN or SIMULATION: GAPS FOUND, then EPIC: {public_ref}. Wrong epic refuses exit 16; missing EPIC refuses exit 17.

## Worktree-State Authority
Task `worktree_path` / branch is actual-code authority in one lane or many. Main is the base/integration target. Without a resolved lane or supplied diff, report missing evidence.

Read the authoritative item spec from the DB:
yoke items get {public_ref} spec

## Task Content
{for each task: task number, title, and body content from yoke workflow-item epic-task body-get}

## Code Changes Per Branch
{for each branch: git diff main...{branch}}

## Worktree Authorities
{for each task: task number, branch/worktree, worktree_path}

## Task Statuses
{output of yoke epic-tasks list --epic PREFIX-N}

## Reviews
{for each task with a review: output of yoke workflow-item epic-task review-get}

## Context Budget Guidance
Use inline tasks, changes and reviews; read the authoritative parent spec without fetching the inline content again.

## Instructions
Focus on:
- Actual exports vs interface contracts
- Naming consistency across tasks
- Merge sequence and generated-file overlap
- Combined state validity after merge

Apply the common contract and return your gap report.
```

## Compressed Integration Prompt

```text
Simulate the integration for epic "{epic-ref}".
Item ID: {public_ref}

## Phase: INTEGRATION (post-execution, pre-merge) — COMPRESSED CONTEXT

All tasks are complete (or: the following tasks are incomplete and should be excluded from path tracing: {list}). Trace actual code across worktrees for integration gaps before merging.

Begin with SIMULATION: CLEAN or SIMULATION: GAPS FOUND, then EPIC: {public_ref}. Wrong epic refuses exit 16; missing EPIC refuses exit 17.

## Worktree-State Authority
Task `worktree_path` / branch is actual-code authority in one lane or many. Main is the base/integration target. Without a resolved lane or supplied diff, report missing evidence.

Task count: {_task_count}. Use the compressed context below.

Read the authoritative item spec from the DB:
yoke items get {public_ref} spec

## Interface Contracts Per Task
{for each task: extracted contracts only}

## Shim Re-Export Contracts
{for each shim-style module named in a task contract or diff stat: parse the explicit
from yoke_core.board.X import (...) block and list every re-exported name,
including public names and underscore-prefixed names such as _BLOCKS. the shim import list is the source of truth;
do not infer exports from child module internals.}

## File Overlap Matrix
{output of overlap query}

## Dependency Edges
{task_num, title, depends_on for each task}

## Worktree Authorities
{for each task: task number, branch/worktree, worktree_path}

## Per-Task Change Summaries
{for each task: one-line summary}

## Diff Stats Per Branch
{for each branch: git diff main...{branch} --stat}

## Commit-Boundary Evidence
{for each discrete-commit or NFR-style AC: task or AC identifier, affected
file path, and one parent-supplied git log --oneline -- {file} line proving
the commit boundary. If no affected file can be discovered, include
commit evidence unavailable: no affected file named. This prompt-supplied
section is allowed evidence; the simulator must not run git log or git blame
itself unless explicitly instructed.}

## Task Statuses
{output of yoke epic-tasks list --epic PREFIX-N}

## Review Summaries
{for each task with a review: verdict line and issue lines only}

## Two-Phase Analysis Protocol

### Phase A — Bounded Preliminary Verdict (no tool calls)
Using only the compressed context above, produce:
1. Preliminary verdict
2. Up to 3 candidate gaps with severity, category, and brief description

### Phase B — Selective Verification (budgeted, max 5 file reads)
After the Phase A verdict, optionally read up to 5 files to verify or refute your candidate gaps.

Rules:
- Only read files directly named in the compressed context unless a contradiction is found
- Use `git diff main...{branch} -- {specific-file}` for individual file diffs
- Upgrade or downgrade severities based on verification
- Produce your final verdict and gap report

## Forbidden Operations
- Broad `git diff` of entire branches
- `ls`, `find`, or `glob` enumeration of directories
- Reading files not named in the compressed context
- Systematic exploration of all branch files
- Git archaeology unless explicitly requested. Parent-supplied
  Commit-Boundary Evidence in this prompt is allowed evidence; do not run
  git log or git blame yourself.

If uncertain about a gap, report GAPS FOUND with the uncertainty noted.

Focus on:
- Actual exports vs interface contracts
- Naming consistency across tasks
- Merge sequence and generated-file overlap
- Combined state validity after merge

Apply the common contract and return your gap report.
```
