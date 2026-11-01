---
name: steer
description: "Direct-mode entrypoint — itemless steering loop over a strategy doc, defaulting to CURRENT-PLAN."
argument-hint: "[STRATEGY-DOC-SLUG] [--project P ...]"
---

# /yoke steer [STRATEGY-DOC-SLUG] [--project P ...]

Steer one claimed strategy doc per project (default `CURRENT-PLAN`), staff
workers and keep plan state; never implement.

## Phase map

| Phase | Read before acting |
|---|---|
| Resolve doc, take paired seat | [scope-and-authority.md](scope-and-authority.md) |
| Attach fleet watcher | [watching.md](watching.md) |
| Continuous pass | [loop.md](loop.md) |
| Triage report findings | [fleet-findings.md](fleet-findings.md) |
| Dependencies, quiet workers, restaff | [worker-lifecycle.md](worker-lifecycle.md) |
| Launch, message, rework | [worker-launch.md](worker-launch.md) |
| Level and model choice | [model-selection.md](model-selection.md) |
| Blitz document handoff | [blitz-handoff.md](blitz-handoff.md) |
| Batch merged delivery | [release-batches.md](release-batches.md) |
| Stop, hand off, release | [close-out.md](close-out.md) |
| Command lookup | [function-reference.md](function-reference.md) |

## Standing rules

- Root-cause each defect (why now, what changed), using subagents when
  nontrivial, before proposing a minimal fix for operator approval.
- No doc-less steering, no `/yoke feed`. Keep each item's pinned workflow.
- File software work only as dashes with `yoke dash ... --strategy-doc SLUG`;
  keep existing items' workflows and explicit operator workflow choices intact.
- Workers merge; only the steerer creates deployment runs.
- Confirm a run carried a commit before calling it live.
- Check infrastructure is in use before taking work on it.
- Each reply lists outstanding operator actions and what they unblock.
- Before filing, have the operator write goals and a high-level plan in the
  strategy doc, defined enough for a large set of parallel dashes. Break its
  well-defined parts into proposed dashes with correct dependency edges.
- Vet each proposal with a subagent for overengineering: simplify or delete
  before adding machinery; prefer no new DB fields or migrations. Present
  each vetted dash as very short, plain-language bullets, using real code
  names where useful. File only after explicit operator approval, then keep
  the strategy doc current with what was filed.
- Present every operator decision one at a time with context and a
  recommendation. Before filing or amending major scope, name what it adds,
  why, and the simplest alternative: recurring processes, DB fields/tables
  or migrations, services, infrastructure, dependencies, or a new mechanism
  where one could be reused. Get explicit approval; ask PR reviewers to
  check these too. Continue independent work while a decision waits.

Start: [scope-and-authority.md](scope-and-authority.md).
