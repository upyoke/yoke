# Lifecycle Runtime — Workflow Registry

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [Workflows](index.md) > Lifecycle
<!-- /yoke:breadcrumbs -->

> **Canonical source:** `workflow_runtime.py` loads an item's immutable
> `workflow_id` / `workflow_version_id` pin. Registry definitions are served by
> `yoke workflows definition get`.

This document describes the runtime contract. Definitions own ordered stages,
labels, terminal stages, gates, policies, entry surfaces, and registered
skill bindings. Live transition, frontier, scheduler, QA, approval, and
delivery paths all interpret the item's pin.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Item stage authority

Do not copy a progression into operator logic or documentation. Use
`yoke workflows definition get` for current definitions. A live item loads the
exact pinned version, so a newer one cannot alter work in flight, and a forward
move it does not declare is refused before the target stage materializes.
Backward rework uses `definition.stages` order and needs no declared edge:
`yoke_core.domain.workflow_declared_transitions.undeclared_forward_transition`
checks only forward moves. The holder uses `yoke lifecycle transition` to return
to the requested earlier stage; ordinary claim and target-stage checks still apply.

### Exceptional Item States

These are reachable from multiple points and are not part of the normal forward progression:

- `cancelled`
- `stopped`
- `failed`

> Item-level **blocked** is not a lifecycle status. It is an orthogonal
> flag-and-reason pair on the item that preserves the lifecycle position
> (cross-reference: see your `items` packet stanza for the
> blocked/blocked_reason columns). Set it via
> `yoke items block PREFIX-N --reason "<reason>"`; clear via
> `yoke items unblock PREFIX-N`.
> The board renders blocked items in their own section and the frontier
> routes them to WAIT. The doctor health checks `HC-blocked-status-drift`
> and `HC-blocked-flag-consistency` surface leftover flags and
> legacy `status='blocked'` rows. **Epic-task** `blocked` stays
> as a status. Full architectural-why (yoke source repo):
> `docs/archive/decisions/blocked-flag-retirement.md`.

## Canonical Epic Task Progression

Epic tasks mirror the implementation-family vocabulary:

```text
planning
-> plan-drafted
-> refining-plan
-> planned
-> implementing
-> reviewing-implementation
-> reviewed-implementation
-> polishing-implementation
-> implemented
-> release
-> done
```

Task exceptional states:
- `blocked`
- `stopped`
- `failed`

Epic tasks do **not** use item-only statuses such as `cancelled`.

## Ownership Boundaries
### Definition-bound segments

At a live item stage, the owner is the registered skill binding whose
half-open interval contains that stage:
`from_stage_id <= current_stage < through_stage_id`. Stage names do not select
the skill by themselves, and a workflow name is never a substitute for
reading the pinned version.

The current built-in definitions reuse stage ids such as `idea`,
`refining-idea`, `planning`, and `planned`, but each definition decides which
of those stages exists, their order, and the skill that owns the segment.

### Items are created with their spec

Every create path — `/yoke idea`, `/yoke onboard`, `/yoke curate`,
`yoke dash`, `yoke task`, `yoke items create`, the web form and
`POST /v1/items` — saves the title and spec in one write. The shared create
validation (`yoke_core.domain.mutations_create.prepare_create`) refuses a
missing spec, or one that only repeats the title, with `spec_required` and
the `--spec-file PATH` / `--stdin` repair. The spec states the agreed
outcome; refinement adds detail later. `/yoke idea` still takes a draft work
claim right after creation so no other session refines it mid-authoring.

Items left title-only by an older release wait on the frontier labelled
**Needs a spec** (`needs_spec` on the blocked row), with the command that
writes the spec or cancels the item. `yoke_core.domain.item_spec_completeness`
owns the title-only test, and the doctor check `HC-items-needing-spec` lists
those items.

The filer owns `entry_surface`: skills pass `harness_skill`; Task/Dash
commands default to `cli`. For direct skill intake after reading the target
workflow's execution instructions (`items.create`):
```text
yoke dash "<title>" --spec-file /tmp/dash-spec.txt --entry-surface harness_skill --execution-instructions-considered
```
Task uses `yoke task` with the same flags; planned intake uses `/yoke idea`,
which sets session mode `idea` before filing with `harness_skill`.
Authenticated caller, allowed workflow surfaces, spec acceptance and
execution-instruction attestation remain required; a surface grants no authority.

### Implementation and review

- `implementing` means work is actively being built.
- `reviewing-implementation` means coding/self-verification is complete and the branch is in the deliberate review/fix loop.
- `reviewed-implementation` means meaningful implementation review passed and the work is queued for finishing polish.

When a definition declares this loop, its active skill binding drives it.
For example, current definitions bind either `implement`, `conduct`, or a direct
skill across implementation work; the stage name alone does not choose one.

**Claim continuity across transient SessionEnd.** A Claude Desktop SessionEnd
event (laptop sleep, app reload, idle timeout) never destroys mid-flight
claims: the hook runs the non-destructive `end_session_if_empty`, which ends a
session only when it holds nothing — no active claim, session-owned document
lock, keep-alive hold, pending launch delivery, or in-flight wake delivery.
A session holding any of those is reported as skipped and stays live. Destructive ends are
explicit operator calls (`session-end --release-claims`); releases record
`agent_presence_evidence` on the terminal events. On reactivation, conditional
auto-reacquire restores prior session_ended claims within
`session_reactivation_reacquire_window_s` when no conflicting holder exists.
The stale-session sweep can end idle claimless sessions; it preserves every
active work-claim holder regardless of heartbeat, park, or process state.
See `docs/harness-substrate.md` for
the full contract.

### Polish handoff

For definitions that declare and bind these stages:

- `polishing-implementation` means the registered `polish` segment owns the finishing pass.
- `implemented` means the branch is implementation-complete and ready for the next definition-bound handoff.

### Merge and deployment

Current definitions whose `policies.delivery` is `release_stage` bind `usher`
across their delivery tail. Their run-backed path uses
`implemented -> release -> done`; their no-flow path closes from
`implemented -> done`. Definitions with `continuous_slice_actions` or
`after_merge_action` have a different tail and do not inherit those stages.

Read the pinned definition before invoking `usher`; it owns a boundary only
when an active skill binding says so.

## What The Statuses Mean

| Status | Meaning |
|---|---|
| `idea` | Filed but not yet shaped into an execution-ready item |
| `refining-idea` | The item is being clarified and tightened |
| `refined-idea` | Idea-level shaping is complete |
| `planning` | Planning or decomposition has started in a workflow that declares this stage |
| `plan-drafted` | An initial plan or generated-task decomposition exists |
| `refining-plan` | Plan is being revised after critique/simulation |
| `planned` | The plan is accepted and ready for the next bound skill |
| `implementing` | Engineering work is actively in progress |
| `reviewing-implementation` | Review/fix/verify loop is in progress |
| `reviewed-implementation` | Implementation review passed; ready for polish |
| `polishing-implementation` | Finishing pass is in progress |
| `implemented` | Implementation complete; ready for usher/merge/deploy handoff |
| `release` | Deployment run is actively executing |
| `done` | Delivery complete. When an item finished is the `item_status_transitions` row that put it here, not `merged_at`, which dates the code landing that close-out can trail by a day |
| `cancelled` | Item was intentionally abandoned |
| ~~`blocked`~~ | **Not a lifecycle status for items.** Items use an orthogonal blocked flag that preserves lifecycle status (cross-reference: see your `items` packet stanza). Epic-task `blocked` is a status. |
| `stopped` | Work halted unexpectedly or intentionally paused. Terminal for resource release, so claims and lanes are freed, but a pause is not an ending: it never counts as finished work and stays out of Done counts and "finished" card text |
| `failed` | Work concluded in failure and needs intervention |

## QA And Lifecycle

QA evidence is recorded in `qa_requirements`, `qa_runs`, and `qa_artifacts`,
not in lifecycle status names. A transition is QA-gated only when the target
stage in the item's pinned definition references the `qa_verification` gate.
Project and item attachments materialize the requirements for that transition;
the stage name alone does not imply a fixed QA recipe.

## See Also

- [commands.md](../agents/commands.md)
- [charge-frontier.md](../strategy/charge-frontier.md)
- [qa-platform.md](../reference/qa-platform.md)
- [db-reference.md](../reference/db-reference.md)


## Related

- [Transitions and routing](transitions.md)
