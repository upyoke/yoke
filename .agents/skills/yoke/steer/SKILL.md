---
name: steer
description: "Direct-mode entrypoint — itemless steering loop over a strategy doc, defaulting to CURRENT-PLAN."
argument-hint: "[STRATEGY-DOC-SLUG] [--project P ...]"
---

# /yoke steer [STRATEGY-DOC-SLUG] [--project P ...]

Steer one claimed strategy doc per project (default `CURRENT-PLAN`): staff
workers and keep plan state. The steerer never implements.

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
- File new work with `yoke dash ... --strategy-doc SLUG`.
- Workers merge; only the steerer creates deployment runs.
- Confirm a run carried a commit before calling it live.
- Check infrastructure is in use before taking work on it.
- Every operator-visible reply lists each outstanding operator action and what
  it unblocks, inside the normal reply; never a separate nag turn.
- Before filing or amending a spec that makes a major design or scope
  decision, present it to the operator as a named scope decision (what it
  adds, why, and the simplest alternative) and wait for an explicit yes. Major
  decisions include at least: a recurring process (loop, scheduler, cron,
  background job, poller); a new table, new fields or columns, or any database
  migration; a new service; new infrastructure (cloud resources, instances,
  queues, Lambdas); a new external dependency; and any new mechanism where an
  existing one could be reused. When asking a reviewer to vet a PR, ask
  whether it adds any of these.
- Ask only at the missing-doc gate, a scope decision or a reserved operator
  decision.

Start: [scope-and-authority.md](scope-and-authority.md).
