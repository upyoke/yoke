---
name: advance
description: "Internal sub-skill: advance a backlog item to the next status in its lifecycle, or to a specific target status."
argument-hint: "{PREFIX-N} [status]"
---

# Internal sub-skill called by implement, conduct, polish, and usher for
# their status writes. Its only operator form is the skip flags in
# arguments.md; implementation entry is the `implement` stage skill.

# /yoke advance {PREFIX-N} [status]

Advance a backlog item's status forward through its pinned workflow. The shared
lifecycle interpreter validates every transition from the item's immutable
workflow version; this sub-skill runs the target stage's gates, QA phases, and
worktree-scoped commit around that write for the calling skill.

`{PREFIX-N}` accepts prefixed, zero-padded, or bare numeric ids. `[status]` is
an optional target status; omitted, it advances one stage.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Phase map — read one file, at the phase it governs

| Phase | You are here when | Read before acting |
|---|---|---|
| 0–2. Skip, parse, target | The invocation just arrived | [`parse-and-target.md`](parse-and-target.md) |
| 4. Phase dispatch | A forward transition is confirmed | [`phase-dispatch.md`](phase-dispatch.md) |
| — Flags | The invocation carries `--env`, `--force`, or a skip flag | [`arguments.md`](arguments.md) |

The phase-dispatch step names the reference the target actually needs
([`preflight.md`](preflight.md), [`browser-qa.md`](browser-qa.md),
[`project-e2e.md`](project-e2e.md), [`finalize.md`](finalize.md)); read only
the ones it selects. [`workflow-context.md`](workflow-context.md) resolves the
pin and is read once, from step 1.

## Standing rules — these bind at every phase

**Lifecycle authority.** The item's `workflow_id` and `workflow_version_id`
select the immutable definition. Never reconstruct a progression in this skill.
Read the served definition for navigation and let
`lifecycle.transition.execute` enforce the pinned version, stage order, and
every listed and structural gate ([`preflight.md`](preflight.md)); its
response names the bound-skill handoff a transition crosses.

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

**Never stop at a handoff menu.** Return to the calling skill's loop after the
status write. Do not surface the worktree path and stop, and never ask "Want me
to review now?" unless a real blocker prevents continued work.

## Start

The calling skill already stamped the session mode and holds the claim this
sub-skill needs. Read [`parse-and-target.md`](parse-and-target.md) and follow
it.
