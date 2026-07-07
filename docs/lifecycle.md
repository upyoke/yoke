# Lifecycle State Machine — Software Delivery Workflow Family

> **Canonical source:** [packages/yoke-core/src/yoke_core/domain/lifecycle.py](/Users/dev/yoke/packages/yoke-core/src/yoke_core/domain/lifecycle.py) is authoritative. This document is the human-readable companion.

This document describes the current delivery lifecycle for Yoke work. The canonical implementation-family model is enforced by the Python lifecycle registry and the live write paths.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug not worth a ticket, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Canonical Item Progressions

Yoke uses two canonical item progressions selected by workflow type.

### Issue-workflow-type

```text
idea
-> refining-idea
-> refined-idea
-> implementing
-> reviewing-implementation
-> reviewed-implementation
-> polishing-implementation
-> implemented
-> release
-> done
```

### Epic-workflow-type

```text
idea
-> refining-idea
-> refined-idea
-> planning
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

### Exceptional Item States

These are reachable from multiple points and are not part of the normal forward progression:

- `cancelled`
- `stopped`
- `failed`

> Item-level **blocked** is not a lifecycle status. It is an orthogonal
> flag-and-reason pair on the item that preserves the lifecycle position
> (cross-reference: see your `items` packet stanza for the
> blocked/blocked_reason columns). Set it via
> `/yoke block YOK-N "<reason>"`; clear via `/yoke unblock YOK-N`.
> The board renders blocked items in their own section and the frontier
> routes them to WAIT. The doctor health checks `HC-blocked-status-drift`
> and `HC-blocked-flag-consistency` surface any row that still carries
> the legacy lifecycle position. **Epic-task** `blocked` semantics stay
> as a status. Full architectural-why:
> [`docs/archive/decisions/blocked-flag-retirement.md`](archive/decisions/blocked-flag-retirement.md).

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

### Pre-implementation shaping

- `idea -> refining-idea -> refined-idea` belongs to the ideation / refinement path.
- Epic-only planning states (`planning`, `plan-drafted`, `refining-plan`, `planned`) belong to the planning path.

### `idea -> refine` handoff: two-layer guard against title-only dispatch

`/yoke idea` writes the row in two phases — `items add` lands the YOK-N
row with empty `spec`, and `body-and-sync.md` writes the structured spec
fields a few seconds later. The window between the two phases is
unprotected unless both layers below hold:

- **Layer 1 — claim-on-create (live-race fix).** `infer-and-create.md`
  step 5b acquires a draft work claim with reason `draft-in-progress`
  immediately after `items add` returns the YOK-N id, and
  `body-and-sync.md` step 10b releases it with reason `idea-complete`
  once the spec/body, AC normalization, and File Budget have landed.
  The release path canonicalizes `idea-complete` → `handed_off` for
  schema storage and preserves the original intent on the `WorkReleased`
  event. While the draft claim is held, another harness's
  `session-offer` filters the row out via the standard live-claim
  conflict gate. Held duration is recorded on the `IdeaClaimHeld`
  event for doctor and Ouroboros observability.
- **Layer 2 — body-completeness skip on the frontier (structural
  defense).** `runtime/api/domain/frontier_compute.py` calls
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

This implementation/review loop may be driven by `conduct` or by direct `advance` flows, but the stored statuses are the same.

**Claim continuity across transient SessionEnd.** A Claude Desktop SessionEnd
event (laptop sleep, app reload, idle timeout) no longer destroys mid-flight
claims when the heartbeat is fresh or a chain checkpoint still has budget.
`yoke_core.domain.sessions_lifecycle_destructive_guard.evaluate_destructive_end`
inspects both signals and either defers the destructive end
(`HarnessSessionEndDeferred`) or, on a permanent end, lets the release path
run with the truthful `claude_session_end_hook_fired` audit rationale plus
`agent_presence_evidence`. On reactivation, conditional auto-reacquire restores
prior session_ended claims when no conflicting holder exists. See
`docs/harness-substrate.md` for the full contract.

### Polish handoff

- `polishing-implementation` means routed polish owns the finishing pass.
- `implemented` means the branch is implementation-complete and ready for merge/deploy handoff.

### Merge and deployment

- `implemented -> release -> done` is the normal post-merge path for items with deployment runs.
- `implemented -> done` is the direct path for no-flow / no-stage delivery where no run-backed release phase is needed.

`usher` owns the `implemented` through `done` boundary.

## What The Statuses Mean

| Status | Meaning |
|---|---|
| `idea` | Filed but not yet shaped into an execution-ready item |
| `refining-idea` | The item is being clarified and tightened |
| `refined-idea` | Idea-level shaping is complete |
| `planning` | Epic-only planning has started |
| `plan-drafted` | Initial epic plan/task decomposition exists |
| `refining-plan` | Plan is being revised after critique/simulation |
| `planned` | Epic plan is accepted and ready for implementation entry |
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

QA evidence is recorded in `qa_requirements`, `qa_runs`, and `qa_artifacts`, not in lifecycle status names.

Important consequences:

- Entering `reviewing-implementation` and progressing to `reviewed-implementation` depends on QA evidence and review completion.
- Browser screenshot QA runs as the final gate before `reviewed-implementation` and again as the final gate before `implemented`; post-deploy requirements gate the final `done` transition.

## Post-Merge Behavior

### No-flow / internal delivery

For items whose delivery does not require a run-backed deployment:

```text
implemented -> done
```

The code is already live once merged, so `release` is skipped.

### Run-backed deployment flows

For items enrolled in deployment runs:

```text
implemented -> release -> done
```

Operationally:

- item stays `implemented` until the deployment run actually begins execution
- item moves to `release` while the run is executing
- item moves to `done` when the run succeeds and blocking post-deploy/manual-acceptance requirements are satisfied

## Command Families

Two delivery command families cover the entire item progression. Use the right family for the item's workflow type — mixing them produces routing failures.

### Issue command family

For `type=issue` items:

```text
/yoke refine YOK-N (idea -> refining-idea -> refined-idea)
/yoke advance YOK-N implementation
 (refined-idea -> implementing, opens worktree in the SAME session — no relaunch; work-claim is the authority)
 continue in worktree (implementing -> reviewing-implementation -> reviewed-implementation)
/yoke polish YOK-N (reviewed-implementation -> polishing-implementation -> implemented)
/yoke usher YOK-N (implemented -> release -> done, or implemented -> done)
```

Issues never visit `planning`, `plan-drafted`, `refining-plan`, or `planned`. `/yoke shepherd` is not part of the issue family.

### Epic command family

For `type=epic` items:

```text
/yoke refine YOK-N (idea -> refining-idea -> refined-idea)
/yoke shepherd YOK-N (refined-idea -> planning -> plan-drafted)
/yoke refine YOK-N (plan-drafted -> refining-plan -> planned; plan refinement)
/yoke conduct YOK-N (planned -> implementing; task-lane activation continues in the SAME session — each subagent dispatch acquires its own work-claim — then drives to reviewed-implementation)
/yoke polish YOK-N (reviewed-implementation -> polishing-implementation -> implemented)
/yoke usher YOK-N (implemented -> release -> done, or implemented -> done)
```

Epics pass through `/yoke refine` twice: once for the idea spec and again for the technical plan after Shepherd drafts it.

## Command Boundary Summary

| Command | Owns transitions | Applies to |
|---|---|---|
| `/yoke refine` | `idea -> refining-idea -> refined-idea`, `plan-drafted -> refining-plan -> planned` | issues and epics |
| `/yoke shepherd` | `refined-idea -> planning -> plan-drafted` (quality-gated planning) | **epics only** |
| `/yoke advance ... implementation` | `refined-idea -> implementing` (issues), `planned -> implementing` (with `--force`). Creates or re-enters the worktree unless `--no-worktree`; same harness session continues into implementation/review under the work-claim it holds on the item. | **issues only** as primary entry; epics use conduct |
| `/yoke conduct` | `planned -> implementing -> reviewing-implementation -> reviewed-implementation`; task-lane activation provisions per-lane worktrees and each subagent dispatch acquires its own work-claim. | **epics only** (Engineer/Tester loop) |
| `/yoke polish` | `reviewed-implementation -> polishing-implementation -> implemented` | issues and epics |
| `/yoke usher` | `implemented -> release -> done` or `implemented -> done` | issues and epics |

The review phase (`implementing -> reviewing-implementation -> reviewed-implementation`) happens in the same worktree as implementation. Issues stay under `/yoke advance` re-entry; epics stay under `/yoke conduct`. Neither command family treats `reviewing-implementation` as a manual-only checkpoint — the loop continues until review actually passes or a real blocker appears.

`reviewed-implementation` and `implemented` are handoff boundaries. `/yoke polish` and `/yoke usher` start as fresh command entrypoints at those statuses; the prior command does not carry claim ownership across the boundary.

### Claim release at handoff — visible failure

The advance finalize step that hands the claim across these boundaries (`yoke_core.api.service_client release-work-claim --item YOK-N`) is best-effort: when it cannot release (cross-session mismatch, claim already terminal, item never claimed, or the underlying domain validator raised), the advance still succeeds because the status transition has already committed. But the failure is no longer silent — finalize prints a single `Warning: claim release failed for YOK-N (intent=X, exit=Y)` line, the CLI writes failure-specific detail to stderr, and an `ItemClaimReleaseFailed` event (severity WARN) carries `item_id`, `caller_session_id`, `holder_session_id`, `failure_reason` (`not_owned` / `already_terminal` / `item_not_found` / `domain_error`), `target_status`, and `release_reason_intent`. Exit codes are distinct (`3`/`4`/`5`/`6`) so wrappers can branch. Operators investigating "why didn't the claim release?" should query the events ledger first: `yoke events query --item YOK-N --event-name ItemClaimReleaseFailed`.

## Routing And Session Offer

Routing decisions (which command to invoke for an item at a given status, which lane to run in, how `/yoke do` chains) are owned by the core scheduler and session-offer path, not by this document. The canonical sources are:

- [session-offer-contract.md](./session-offer-contract.md) — request/response envelope, `NextAction` shape, chainability rules
- [charge-frontier.md](./charge-frontier.md) — frontier computation, status-to-adapter mapping, ranking
- [packages/yoke-core/src/yoke_core/domain/scheduler_routing.py](/Users/dev/yoke/packages/yoke-core/src/yoke_core/domain/scheduler_routing.py) — the `next_step` function that turns a status into a command
- [packages/yoke-core/src/yoke_core/domain/sessions.py](/Users/dev/yoke/packages/yoke-core/src/yoke_core/domain/sessions.py) — shared session-offer path that emits `HarnessSessionOffered` and `NextActionChosen`

Agents reading the lifecycle should treat those files as authoritative for "which command runs next?" and use the tables above only for "which statuses does that command touch?".

## See Also

- [commands.md](./commands.md)
- [session-offer-contract.md](./session-offer-contract.md)
- [charge-frontier.md](./charge-frontier.md)
- [qa-platform.md](./qa-platform.md)
- [db-reference.md](./db-reference.md)
