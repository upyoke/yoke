---
name: steer
description: "Direct-mode entrypoint — itemless steering loop over a strategy doc, defaulting to CURRENT-PLAN."
argument-hint: "[STRATEGY-DOC-SLUG] [--project P ...]"
---

# /yoke steer [STRATEGY-DOC-SLUG] [--project P ...]

Itemless steering loop. A harness session claims the steering scope of one
strategy document — `CURRENT-PLAN` unless the operator names another — holds
that document, and keeps that scope moving:
read the standing plan, reconcile it with the live frontier, consume worker
reports, write plan-level state back into the doc, hand work to executors,
staff unpicked runnable items, and escalate only decisions that need a human.
The coordinator never implements. Steering covers every pinned workflow;
each item keeps its own workflow and routed entrypoint from intake through
its live merge or release boundary.

Steering means continuous small course corrections while something else
provides the power. The stored claim kind is a **steering-scope claim**;
the skill id is **steer**. Do not invent a "steer claim".

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Phase map — read one file, at the phase it governs

| Phase | You are here when | Read before acting |
|---|---|---|
| 1–3. Parse, read the doc, take the seat | `/yoke steer` was just invoked | [`scope-and-authority.md`](scope-and-authority.md) |
| 4. Run the standing loop | Both halves of the seat are held | [`loop.md`](loop.md) |
| 5. Close out | An explicit stop, or an orderly handoff | [`close-out.md`](close-out.md) |
| — Staff a worker | The loop is about to launch or judge one | [`worker-lifecycle.md`](worker-lifecycle.md) |
| — Pick a model for a launch | A launch needs a model or effort choice | [`model-selection.md`](model-selection.md) |
| — Watch the fleet | The loop is arming or reading the fleet watcher | [`watching.md`](watching.md) |
| — Read a fleet finding | A worker reported something the seat must triage | [`fleet-findings.md`](fleet-findings.md) |
| — Hand a Blitz to its executor | The staffed item's pinned workflow is Blitz | [`blitz-handoff.md`](blitz-handoff.md) |
| — Look up a function id | You need a steering operation's exact envelope | [`function-reference.md`](function-reference.md) |

Do not invoke `/yoke feed`. Feed and steer are unrelated.

## Invariants — these bind from the first action


- **Itemless.** This session holds no work item. One atomic steering acquire
  pairs the steering-scope claim with its strategy-doc lock; together they
  are its authority. The doc and its linked items ARE the surviving state.
- **Vocabulary is steering.** Identifiers, refusal text, and labels use
  steering-scope claim, steering claim holder, steering scope. "Coordinator"
  is acceptable role prose. Never name a durable identifier coordination
  or coordinator. Avoid the bare phrase "steer claim".
- **No new scheduler.** The loop is message wakes plus periodic frontier
  checks through existing surfaces. Do not add or call feed.
- **Every workflow stays itself.** Read each item's pinned `workflow_id` and
  the scheduler's `next_step`; never convert or re-file incoming work to make
  it Dash-shaped. One worker owns that one item across its routed legs.
  Before declaring a capability absent or filing follow-up work, verify
  that pinned workflow (`yoke workflows item get PREFIX-N --json`) and the
  full command path; a named refusal is evidence, a guess is not.
- **Dash is the filing default, not the steering boundary.** New work filed by
  the steerer uses Dash unless it is genuinely laneless, merge-free Task work
  (`yoke task TITLE INSTRUCTION --execution-instructions-considered`), needs
  Issue, Epic, or Blitz structure, or the operator directs another workflow.
  Pass `--strategy-doc {SLUG}` on either so the filed item lands inside this
  seat's scope.
- **Workers merge; the steerer batches delivery.** Worker mandates prohibit
  deployment-run creation. The loop pins one release SHA, deploys batches,
  and completes any item parked at its release boundary afterward.
- **Every response the operator sees states a live outstanding operator
  action** — the item it blocks and what it unblocks — until it resolves
  or the operator asks to mute reminders; fold this into the reply and the
  standing-plan snapshot already produced each pass, never a separate
  alert or an extra turn spent only to repeat it. The moment a server or
  system failure explains the same block, correct the attribution there
  instead of continuing to ask for the human action.
- **Autonomous.** Invoking `/yoke steer` authorizes the loop. Do not wait
  for confirmation before claiming, reading the frontier, acknowledging
  reports, launching workers, or writing the doc — except the documented
  offer-to-create and operator-escalation gates.


The invariants that define what this seat *covers* — scope, document,
membership, and how workers address it — are in
[`scope-and-authority.md`](scope-and-authority.md), read at step 1.

## Start

Read [`scope-and-authority.md`](scope-and-authority.md) and follow it.
