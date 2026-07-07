# Simulate Phase: Canonical Simulator Dispatch Prompts

Use these prompts when invoking the `yoke-simulator` subagent.

## Plan Simulation Prompt

```text
Simulate the plan for epic "{epic-id}".
Item ID: YOK-{item_id}

## Phase: PLAN (pre-sync, pre-implementation)

Trace the planned architecture for integration gaps. No code has been written yet — you are checking the plan's structural soundness.

IMPORTANT: Your response MUST begin with the two-line verdict block — line 1 is SIMULATION: CLEAN or SIMULATION: GAPS FOUND, line 2 is EPIC: YOK-{item_id}. Persistence rejects bodies whose attested epic does not match YOK-{item_id} (exit 16) or that omit the EPIC line entirely (exit 17).

Read the authoritative item spec and plans from the DB:
yoke items get YOK-{item_id} spec
yoke items get YOK-{item_id} technical_plan
yoke items get YOK-{item_id} worktree_plan

## Task Content
{for each task: task number, title, and body content from yoke workflow-item epic-task body-get}

## Context Budget Guidance
The task content above is already inline in this prompt. Do not re-read these task bodies from the DB. You should read the authoritative item spec/plans from the DB.

## Instructions
Focus on:
- Interface contract mismatches between dependent tasks
- Worktree visibility assumptions
- Dependency ordering feasibility
- Environment and runtime assumptions that vary across tasks
- Merge sequence predictions

## Failure Path Analysis
For each modified write path in this epic:
1. What external calls can fail?
2. Under `set -e`, does failure propagate safely or crash the caller?
3. Does the new error model match the old one?
4. Do tests cover the failure case, not just the happy path?

Produce your gap report. Use [CRITICAL], [WARNING], [NOTE] severity prefixes.
```

## Standard Integration Prompt

```text
Simulate the integration for epic "{epic-id}".
Item ID: YOK-{item_id}

## Phase: INTEGRATION (post-execution, pre-merge)

All tasks are complete (or: the following tasks are incomplete and should be excluded from path tracing: {list}). Trace actual code across worktrees for integration gaps before merging.

IMPORTANT: Your response MUST begin with the two-line verdict block — line 1 is SIMULATION: CLEAN or SIMULATION: GAPS FOUND, line 2 is EPIC: YOK-{item_id}. Persistence rejects bodies whose attested epic does not match YOK-{item_id} (exit 16) or that omit the EPIC line entirely (exit 17).

## Worktree-State Authority
A task's resolved worktree checkout is the authority for that task's actual code whether the item/epic has one worktree or many. Main is the base/integration target, not evidence of unmerged task state. Use the task's `worktree_path` / branch when verifying files; if no worktree path or prompt-supplied diff exists, report evidence missing instead of inspecting main as a substitute.

Read the authoritative item spec from the DB:
yoke items get YOK-{item_id} spec

## Task Content
{for each task: task number, title, and body content from yoke workflow-item epic-task body-get}

## Code Changes Per Branch
{for each branch: git diff main...{branch}}

## Worktree Authorities
{for each task: task number, branch/worktree, worktree_path}

## Task Statuses
{output of yoke epic-tasks list --epic <epic-id>}

## Reviews
{for each task with a review: output of yoke workflow-item epic-task review-get}

## Context Budget Guidance
The task content, code changes, and reviews above are already inline in this prompt. Do not re-read them from the DB. You should read the authoritative item spec from the DB.

## Instructions
Focus on:
- Actual exports vs interface contracts
- Naming consistency across tasks
- Merge sequence and generated-file overlap
- Combined state validity after merge

## Failure Path Analysis
For each modified write path in this epic:
1. What external calls can fail?
2. Under `set -e`, does failure propagate safely or crash the caller?
3. Does the new error model match the old one?
4. Do tests cover the failure case, not just the happy path?

Produce your gap report. Use [CRITICAL], [WARNING], [NOTE] severity prefixes.
```

## Compressed Integration Prompt

```text
Simulate the integration for epic "{epic-id}".
Item ID: YOK-{item_id}

## Phase: INTEGRATION (post-execution, pre-merge) — COMPRESSED CONTEXT

All tasks are complete (or: the following tasks are incomplete and should be excluded from path tracing: {list}). Trace actual code across worktrees for integration gaps before merging.

IMPORTANT: Your response MUST begin with the two-line verdict block — line 1 is SIMULATION: CLEAN or SIMULATION: GAPS FOUND, line 2 is EPIC: YOK-{item_id}. Persistence rejects bodies whose attested epic does not match YOK-{item_id} (exit 16) or that omit the EPIC line entirely (exit 17).

## Worktree-State Authority
A task's resolved worktree checkout is the authority for that task's actual code whether the item/epic has one worktree or many. Main is the base/integration target, not evidence of unmerged task state. Use the task's `worktree_path` / branch when verifying files; if no worktree path or prompt-supplied diff exists, report evidence missing instead of inspecting main as a substitute.

This is a large epic ({_task_count} tasks). To preserve context budget for analysis, this prompt provides compressed context instead of full task bodies and full diffs.

Read the authoritative item spec from the DB:
yoke items get YOK-{item_id} spec

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
{output of yoke epic-tasks list --epic <epic-id>}

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

## Failure Path Analysis
For each modified write path in this epic:
1. What external calls can fail?
2. Under `set -e`, does failure propagate safely or crash the caller?
3. Does the new error model match the old one?
4. Do tests cover the failure case, not just the happy path?

Produce your gap report. Use [CRITICAL], [WARNING], [NOTE] severity prefixes.
```
