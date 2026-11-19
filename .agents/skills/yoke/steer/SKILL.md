---
name: steer
description: "Staff and track work from a strategy doc, defaulting to CURRENT-PLAN."
argument-hint: "[STRATEGY-DOC-SLUG] [--project P ...]"
---

# /yoke steer [STRATEGY-DOC-SLUG] [--project P ...]

Steer each named strategy doc (default `CURRENT-PLAN`): one seat per doc, all
held by this session; staff workers and keep plan state; never implement.
Your job is the main-session flow in your startup block; run it until the
user's full scope is done.

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

## Standing rules

- Root-cause each defect (why now, what changed), using subagents when
  nontrivial, before filing a minimal fix.
- No doc-less steering, no `/yoke feed`. Keep each item's pinned workflow.
- File software work only as dashes with `yoke dash ... --strategy-doc SLUG`;
  keep existing items' workflows and explicit operator workflow choices intact.
  A dash with no `--verification-plan` is verified by the project's
  `registered-command-quick` plan when one is registered; name another plan
  with `--verification-plan ID_OR_SLUG`, or `--verification-method none` for none.
- Workers merge; only the steerer creates deployment runs.
- Confirm a run carried a commit before calling it live.
- Check infrastructure is in use before taking work on it.
- End every reply with `Needs you:` and each open operator ask in one line,
  or `Nothing needs you.`
- Record the user's spec and definition of done in the strategy doc as
  given. Never narrow the scope or finish line without the user's OK.
- Before filing, help the user write goals and a high-level plan in the
  strategy doc from their input. Split it into dashes that maximize
  parallelism and minimize calendar time, not necessarily one per subsystem. Give each dash its slice,
  done test, QA requirements and dependency edges. Don't hand-roll waves:
  enter every ordering need as a dependency edge (`yoke items dependency
  add`), only where items share a file or need another's result. Keep chains
  flat, and attach each edge at the earliest stage that works, for max
  throughput.
- Vet each proposal with a subagent for overengineering: simplify or delete
  before adding machinery; prefer no new DB fields or migrations.
  File vetted dashes yourself, then keep the
  strategy doc current with what was filed, summarized in very short,
  plain-language bullets using real code names where useful. Ask the user
  only key decisions, as decision requests.
- Judge done against the user's finish line, not linked items. Keep filing
  and staffing until it is met.
- Vet every item before staffing it, whether you filed it or not. Put vet
  fixes into the spec before staffing; for a filed, unclaimed item, claim it,
  edit its spec, then release it.
- Before filing or amending major scope, name what it adds,
  why, and the simplest alternative: recurring processes, DB fields/tables
  or migrations, services, infrastructure, dependencies, or a new mechanism
  where one could be reused. Get explicit approval through a decision
  request; ask PR reviewers to check these too. Continue independent work while a decision waits.

Start: [scope-and-authority.md](scope-and-authority.md).
