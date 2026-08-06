# Lifecycle Runtime — Workflow Registry

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
`yoke workflows definition get` for current definitions. For a live item, the
transition interpreter loads the exact pinned version so publishing or
selecting a newer version cannot alter work already in flight.

### Exceptional Item States

These are reachable from multiple points and are not part of the normal forward progression:

- `cancelled`
- `stopped`
- `failed`

> Item-level **blocked** is not a lifecycle status. It is an orthogonal
> flag-and-reason pair on the item that preserves the lifecycle position
> (cross-reference: see your `items` packet stanza for the
> blocked/blocked_reason columns). Set it via
> `/yoke block PREFIX-N "<reason>"`; clear via `/yoke unblock PREFIX-N`.
> The board renders blocked items in their own section and the frontier
> routes them to WAIT. The doctor health checks `HC-blocked-status-drift`
> and `HC-blocked-flag-consistency` surface any row that still carries
> the legacy lifecycle position. **Epic-task** `blocked` semantics stay
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

### `idea -> refine` handoff: two-layer guard against title-only dispatch

`/yoke idea` writes the row in two phases — `items add` lands the PREFIX-N
row with empty `spec`, and `body-and-sync.md` writes the structured spec
fields a few seconds later. The window between the two phases is
unprotected unless both layers below hold:

- **Layer 1 — claim-on-create (live-race fix).** `infer-and-create.md`
  step 5b acquires a draft work claim with reason `draft-in-progress`
  immediately after `items add` returns the PREFIX-N id, and
  `body-and-sync.md` step 10b releases it with reason `idea-complete`
  once the spec/body, AC normalization, and every enabled File Budget or
  path-claim artifact has landed.
  The release path canonicalizes `idea-complete` → `handed_off` for
  schema storage and preserves the original intent on the `WorkReleased`
  event. While the draft claim is held, another harness's
  `session-offer` filters the row out via the standard live-claim
  conflict gate. Held duration is recorded on the `IdeaClaimHeld`
  event for doctor and Ouroboros observability.
- **Layer 2 — body-completeness skip on the frontier (structural
  defense).** `yoke_core.domain.frontier_compute` calls
  `yoke_core.domain.idea_body_completeness.is_idea_body_incomplete`
  for every `status='idea'` row and pushes the title-only ones into
  `blocked` with reason `idea-incomplete`. This catches every tail case
  Layer 1 cannot reach: a `/yoke idea` session that crashes between
  the two phases (claim auto-reclaims after the configured stale-heartbeat
  window — `session_stale_ttl_minutes` in machine config; per-executor
  overrides via `session_stale_ttl_minutes_<executor>_override` — but the
  body is still title-only); a manual
  `python3 -m yoke_core.cli.db_router items add` from ad hoc tooling
  that bypasses the claim convention; any future `/yoke idea` variant
  that forgets to acquire the claim. The doctor health check
  `HC-incomplete-idea-bodies` reports items in this state so the
  operator can rescue or freeze them.

### Implementation and review

- `implementing` means work is actively being built.
- `reviewing-implementation` means coding/self-verification is complete and the branch is in the deliberate review/fix loop.
- `reviewed-implementation` means meaningful implementation review passed and the work is queued for finishing polish.

When a definition declares this loop, its active skill binding drives it.
For example, current definitions bind either `advance`, `conduct`, or a direct
skill across implementation work; the stage name alone does not choose one.

**Claim continuity across transient SessionEnd.** A Claude Desktop SessionEnd
event (laptop sleep, app reload, idle timeout) never destroys mid-flight
claims: the hook runs the non-destructive `end_session_if_empty`, which only
ends sessions holding no active claims and no chain-pending budget — sessions
with either are reported as skipped and stay live. Destructive ends are
explicit operator calls (`session-end --release-claims`) and fail closed with
`CHAIN_PENDING` while a chainable checkpoint still has budget, unless
`override_chain_end=True` plus a rationale is supplied; releases record
`agent_presence_evidence` on the terminal events. On reactivation, conditional
auto-reacquire restores prior session_ended claims within
`session_reactivation_reacquire_window_s` when no conflicting holder exists;
truly dead sessions are reclaimed by the stale-session sweep
(`session_stale_ttl_minutes`). See `docs/harness-substrate.md` for the full
contract.

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
| `done` | Delivery complete |
| `cancelled` | Item was intentionally abandoned |
| ~~`blocked`~~ | **Not a lifecycle status for items.** Items use an orthogonal blocked flag that preserves lifecycle status (cross-reference: see your `items` packet stanza). Epic-task `blocked` is a status. |
| `stopped` | Work halted unexpectedly or intentionally paused |
| `failed` | Work concluded in failure and needs intervention |

## QA And Lifecycle

QA evidence is recorded in `qa_requirements`, `qa_runs`, and `qa_artifacts`,
not in lifecycle status names. A transition is QA-gated only when the target
stage in the item's pinned definition references the `qa_verification` gate.
Project and item attachments materialize the requirements for that transition;
the stage name alone does not imply a fixed QA recipe.

## Post-Merge Behavior

### No-flow / internal delivery

For a current `release_stage` definition whose delivery does not require a
run-backed deployment:

```text
implemented -> done
```

The code is already live once merged, so `release` is skipped.

### Run-backed deployment flows

For a current `release_stage` definition enrolled in a deployment run:

```text
implemented -> release -> done
```

Operationally:

- item stays `implemented` until the deployment run actually begins execution
- item moves to `release` while the run is executing
- item moves to `done` when the run succeeds and blocking post-deploy/manual-acceptance requirements are satisfied

### Terminal items are immutable

Once an item reaches a terminal stage its records are frozen. This is
deliberate, not an oversight, and it is enforced structurally rather than by
convention: the ordinary scalar-write path requires the item's work claim,
and a work claim cannot be acquired against a terminal item
(`INVALID_CLAIM: item N is terminal at workflow stage 'done'`). `--force`
bypasses the frozen-item and gate guards, not the claim check.

The same stance governs the adjacent record types — an unsettled QA record
blocks the terminal transition rather than being corrected afterward, so the
repair happens while the claim is still held. Prefer that shape whenever a
value must be right before an item freezes: gate the transition, do not
reopen the record.

Ad hoc write SQL against the authoritative DB is not an escape hatch here;
it is banned by the governed-mutation contract.

#### The one exception: an unrecorded merge timestamp

A branch that lands outside the merge boundary — a hand-run `gh pr merge`,
for example — leaves `items.merged_at` unset, and the item can then reach a
terminal stage with no record of when it merged. Because terminal records
are immutable, nothing could repair that afterward.

One narrow human-only surface exists for exactly that gap:

```bash
yoke items merge-provenance operator-correct PREFIX-N --merged-at YYYY-MM-DDTHH:MM:SSZ --reason TEXT
```

It fills an unset value on an already-terminal item and does nothing else.
It refuses a hook context (human-only), a non-terminal item, an item whose
`merged_at` is already set, and a timestamp that fails to parse or lies in
the future. Every accepted correction emits a WARN
`OperatorMergedAtCorrection` event carrying the operator reason, written
before the update lands, so the ledger records the action even if the write
then fails. Run `yoke items merge-provenance operator-correct --help` for
the recovery workflow, including how to read the real timestamp off the
merge commit.

A live item never needs this: `yoke merge item PREFIX-N` is the merge boundary
and stamps `merged_at` itself.

Note that nothing currently blocks an item from reaching a terminal stage
with `merged_at` unset — the equivalent gate exists only for epics
(`GATE_EPIC_MERGE`). Extending it to standalone items needs a predicate that
separates a genuine no-change item from one that should have merged, so the
correction surface above is today's answer rather than prevention.

## Registered Skill Boundaries

Commands do not own global status ranges and do not apply by item type. Each
immutable workflow version binds registered skill ids to contiguous stage
segments. For a live item:

1. Run `yoke workflows item get PREFIX-N` to read its workflow id, logical
   version, and current stage.
2. Run `yoke workflows version get WORKFLOW VERSION` to read that exact
   definition.
3. In ordered `stages`, find the one `skill_bindings` row whose interval
   satisfies `from_stage_id <= current_stage < through_stage_id`.
4. Invoke `/yoke <skill_id>` and let the definition's target-stage gate
   references govern each transition.

The registered skills have these behavioral contracts; their source and
target stages always come from the binding:

| Skill id | Segment behavior |
|---|---|
| `refine` | Critique and improve the artifact selected by the pinned policies |
| `shepherd` | Run quality-gated planning for a compatible generated-task policy |
| `advance` | Drive a single implementation lane and its review loop |
| `conduct` | Drive generated task lanes and their integration/review loop |
| `polish` | Perform the definition-bound finishing pass |
| `usher` | Merge and deliver a `release_stage` workflow |
| `dash`, `blitz` | Execute their definition-bound direct-work segments |

Worktree shape also comes from `policies.worktrees`,
`policies.parallelism`, and `policies.generated_children`. A single-lane
skill keeps implementation and review in one claimed worktree; a
task-graph skill provisions the registered worker/integration lanes.

A binding's `through_stage_id` is a handoff boundary. The next skill starts
as a fresh command entrypoint and acquires its own claim; the prior skill
does not carry claim ownership across the boundary.

### Claim release at handoff — visible failure

The implementation-skill finalize step that hands the claim across a
binding boundary is best-effort: when it cannot release (cross-session
mismatch, claim already terminal, item never claimed, or the underlying
domain validator raised), the transition remains committed. The failure is
visible as a `Warning: claim release failed for PREFIX-N (intent=X, exit=Y)` line
and an `ItemClaimReleaseFailed` event carrying the item, caller, holder,
failure reason, target stage, and release intent. Operators investigating a
retained claim should query the events ledger first:
`yoke events query --item PREFIX-N --event-name ItemClaimReleaseFailed`.

## Routing And Session Offer

Routing decisions (which command to invoke for an item at a given status, which lane to run in, how `/yoke do` chains) are owned by the core scheduler and session-offer path, not by this document. The canonical sources are:

- [session-offer-contract.md](./session-offer-contract.md) — request/response envelope, `NextAction` shape, chainability rules
- [charge-frontier.md](./charge-frontier.md) — frontier computation, status-to-adapter mapping, ranking
- `yoke_core.domain.scheduler_routing` — the `next_step` function that turns a status into a command
- `yoke_core.domain.sessions` — shared session-offer path that emits `HarnessSessionOffered` and `NextActionChosen`

Agents reading the lifecycle should treat those files plus the item's pinned
definition as authoritative for "which command runs next?" The tables here
describe skill behavior and shared stage meaning; they do not define an
item's stage graph.

## See Also

- [commands.md](./commands.md)
- [session-offer-contract.md](./session-offer-contract.md)
- [charge-frontier.md](./charge-frontier.md)
- [qa-platform.md](./qa-platform.md)
- [db-reference.md](./db-reference.md)
