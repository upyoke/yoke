---
name: advance
description: "Advance a backlog item to the next status in its lifecycle, or to a specific target status."
argument-hint: "{PREFIX-N} [status]"
---

# Sub-skill called by conduct, usher, do/loop, and routed dispatch.
# The `implementation` form (`/yoke advance PREFIX-N implementation`) is also
# operator-facing for workflows whose pinned definition binds `advance` across
# implementation entry. Other advance targets remain internal-only.

# /yoke advance {PREFIX-N} [status]

Advance a backlog item's status forward through its pinned workflow. The shared
lifecycle interpreter validates every transition from the item's immutable
workflow version; this skill coordinates the surrounding operator journey.

`{PREFIX-N}` accepts prefixed, zero-padded, or bare numeric ids. `[status]` is
an optional target status or advance-target name; omitted, it advances one
stage. The advance target `implementation` runs end to end **in the same
harness session** — worktree creation is a filesystem + DB operation, not a
session boundary — and continues into the implementation sub-skill and the
review loop until `reviewed-implementation`. Stopping at `implementing` and
announcing `/yoke polish` as "next" is the hand-off-to-operator anti-pattern
this contract exists to prevent.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Phase map — read one file, at the phase it governs

| Phase | You are here when | Read before acting |
|---|---|---|
| 0–2. Skip, parse, target | The invocation just arrived | [`parse-and-target.md`](parse-and-target.md) |
| 3. Worktree re-entry | The resolved target re-enters an existing lane | [`reentry.md`](reentry.md) |
| 4. Phase dispatch | A forward transition is confirmed | [`phase-dispatch.md`](phase-dispatch.md) |
| — Flags and evidence-only items | The invocation carries `--env`, `--no-worktree`, `--force`, or a skip flag, or an evidence-only item hit the empty-branch guard | [`arguments.md`](arguments.md) |

The phase-dispatch step names the reference the target actually needs
([`preflight.md`](preflight.md), [`browser-qa.md`](browser-qa.md),
[`project-e2e.md`](project-e2e.md), [`finalize.md`](finalize.md)); read only
the ones it selects. [`workflow-context.md`](workflow-context.md) resolves the
pin and is read once, from step 1.

## Standing rules — these bind at every phase

**Lifecycle authority.** The item's `workflow_id` and `workflow_version_id`
select the immutable definition. Never reconstruct a progression in this skill.
Read the served definition for navigation and let
`lifecycle.transition.execute` enforce the pinned version, stage order, gates,
and registered skill binding.

**Operator execution instructions.** Obey the
`# Workflow Execution Instructions` operator block at the top of fetched item
content; it layers on top of, and never replaces, the item's own stored spec
and plan.

**Events at every transition.** Status transitions are significant system
moments. When investigating transition failures, query the events table:
`yoke events query --item PREFIX-N`. The events table captures
`ItemStatusChanged` events with full context.

**Verify before claiming done (P-9).** The done-transition must confirm every
AC is addressed, not just the core implementation. Execution-type deliverables
(running a script, configuring secrets) need explicit verification separate
from code correctness (P-52).

**Never stop at a handoff menu.** Re-entry targets resume their loop in the
recovered worktree. Do not surface the worktree path and stop, and never ask
"Want me to review now?" unless a real blocker prevents continued work.

## Start

Read [`parse-and-target.md`](parse-and-target.md) and follow it.
