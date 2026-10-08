---
name: implement
description: "Implement an item across the stages its workflow binds to implement: engine entry, implementation, and the review loop to the binding's handoff."
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "{PREFIX-N} [--no-worktree] [--force] [--qa-bypass]"
---

# /yoke implement {PREFIX-N}

Stage skill for the segment a pinned workflow binds to `implement` — for an
issue, `refined-idea` up to `reviewed-implementation`. The same harness session
carries the whole segment, with no relaunch: implementation entry through the engine, the
implementing sub-skill, and the review loop until the binding's handoff stage.
There is no target argument: the item's live stage decides where the skill
starts or resumes. Worktree creation is a filesystem and database operation,
not a session boundary, so stopping at `implementing` and announcing a later
step as "next" is the hand-off-to-operator anti-pattern this contract exists
to prevent.

`{PREFIX-N}` requires a complete public ref; bare numbers are refused. The flags are
read only at implementation entry; [`entry.md`](entry.md) owns them.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Phase map — read one file, at the phase it governs

| Phase | You are here when | Read before acting |
|---|---|---|
| 1. Resolve and enter | The invocation just arrived | [`entry.md`](entry.md) |
| 2. Re-enter the lane | The live stage is past the binding's entry stage | [`reentry.md`](reentry.md) |
| 3. Implement | The lane exists and the item is `implementing` | [`implementing/SKILL.md`](implementing/SKILL.md) |
| 4. Review and hand off | Coding and self-verification are complete | [`review.md`](review.md) |
| — Evidence-only items | The work makes no repository change, or the done transition hit the empty-branch guard | [`evidence-only.md`](evidence-only.md) |

[`worktree.md`](worktree.md), [`activation.md`](activation.md), and
[`environment.md`](environment.md) document the phases the implementation-entry
engine composes. They are its contract, not a per-call recipe; read one only
when diagnosing that phase.

## Standing rules — these bind at every phase

**Lifecycle authority.** The item's `workflow_id` and `workflow_version_id`
select the immutable definition. This skill acts only while the binding whose
half-open interval contains the live stage is `implement`, and only inside that
binding's segment. Read stage ids from the served definition, never from a
remembered progression, and let `lifecycle.transition.execute` enforce the
pinned version, stage order, and gates.

**Operator execution instructions.** Obey the
`# Workflow Execution Instructions` operator block at the top of fetched item
content; it layers on top of, and never replaces, the item's own stored spec
and plan.

**Verify before claiming done.** The review handoff confirms every acceptance
criterion is addressed, not just the core implementation. Execution-type
deliverables (running a script, configuring secrets) need explicit
verification separate from code correctness.

**Never stop at a handoff menu.** Re-entry resumes its loop in the recovered
worktree. Do not surface the worktree path and stop, and never ask "Want me to
review now?" unless a real blocker prevents continued work.

## Start

Stamp the session mode on entry so a claimed item at the binding's entry stage
paints its first working stage active:

```text
yoke sessions touch --mode implement
```

Read [`entry.md`](entry.md) and follow it.

A `handoff` with `reason=level_change` takes precedence over a release wait.
Follow the harness-neutral Stage-level handoff rule in
`.yoke/docs/reference/session-level-routing.md`; workers may launch their own successor.
