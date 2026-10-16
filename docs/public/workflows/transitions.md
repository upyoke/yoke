# Workflow transitions and routing

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [Workflows](index.md) > Transitions and routing
<!-- /yoke:breadcrumbs -->

Follow post-merge transitions, registered skill boundaries and explicit staffing.

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
(`INVALID_CLAIM: PREFIX-N is terminal at workflow stage 'done'`). `--force`
bypasses the frozen-item and gate guards, not the claim check.

The same stance governs the adjacent record types — an unsettled QA record
blocks the terminal transition rather than being corrected afterward, so the
repair happens while the claim is still held. Prefer that shape whenever a
value must be right before an item freezes: gate the transition, do not
reopen the record.

Terminal settlement and code-identity checks count each requirement once, using its newest execution. Older attempts never block; browser reviews use the capture's verdict and identity, excluding detached agent verdict rows. A latest closed, verdict-less execution on a superseded requirement stops blocking only after its successor passes or is discharged; post-deploy proof needs accepted completion-member copies. Refusals name unsettled successors. Latest live executions and active plans still block, and history remains unchanged.

Ad hoc write SQL against the authoritative DB is not an escape hatch here;
it is banned by the governed-mutation contract.

#### The one exception: an unrecorded merge timestamp

A branch that lands outside the merge boundary — a hand merge outside Yoke,
for example — leaves `items.merged_at` unset, and the item can then reach a
terminal stage with no record of when it merged; terminal records being
immutable, nothing could repair that afterward. One narrow human-only
surface exists for exactly that gap:

```bash
yoke items merge-provenance operator-correct PREFIX-N --merged-at YYYY-MM-DDTHH:MM:SSZ --reason TEXT
```

It fills an unset value on an already-terminal item and nothing else, refusing
a hook context (human-only), a non-terminal item, an item whose `merged_at` is
already set, and a timestamp that fails to parse or lies in the future.
`--pr-number N` repairs the same provenance's other half — which pull request
carried the landing — for the landings close-out could not read for itself;
that replacement is verified merged against GitHub first, and the predecessor's
stamps drop with it. Each accepted correction emits its WARN event
(`OperatorMergedAtCorrection`, `OperatorLandingPullRequestCorrection`) carrying
the operator reason before the write lands, so the ledger records the action
even if that write then fails.
`yoke items merge-provenance operator-correct --help` has both workflows.

`yoke merge item PREFIX-N` is the live item's merge boundary ([landing notices and recovery](../github/merge-queue-landings.md))
and stamps `merged_at` from the landing merge commit's own time rather than from when close-out ran, so a re-entered close-out writes the same answer and an item that lands a second time reports that landing instead of its predecessor's. Both boundaries do this: the standalone engine reads the merge it just made, and the queue close-out waits until its merge-group receipt names the merge before stamping, so a queue project is not the one left dating an item to a landing it has replaced. Where the control plane observed the landing itself, that observation wins over the commit: a queue merge commit is created when the train forms and merged minutes later, so `merge_queue_landed_at` is the truer moment and the supersede prefers it. On a merge-queue project close-out need not be the process that sees the merge — the pull request number is recorded when that pull request opens, and the control-plane observer stamps `merged_at` and the merge-queue landing columns from GitHub's own merge time. A worker whose wait died therefore leaves a recorded landing rather than an untouched-looking item: the fleet report reports it as landed without close-out, and re-entering `yoke merge item PREFIX-N` closes out from those recorded facts only when the current candidate is already on the base. Recording a landing never advances the stage; close-out stays a claim-holding step. Which pull request the item points at is settled there too: the marker names the pull request the item last armed, and a lane whose commits reach the base under a sibling pull request leaves its own open forever, so close-out repoints the marker at the pull request that carried the merge the base holds the candidate it is closing out under — GitHub's record of that merge, else the subject GitHub wrote on it. It asks that of the candidate in hand, and the evidence record — the commit, the merge and the file set — describes that same landing: a lane that landed twice has both candidates on the base, each under a merge of its own, so close-out keeps the recorded merge receipt only when that receipt landed under the same merge as the candidate. A lane fast-forwarded onto the base, or a rebased copy whose shas the base never saw, names no merge of its own, and there the receipt is still the only identity there is. An ordinary landing finds the marker already right and writes nothing, and a landing with no merge commit to read — a fast-forward or squash — or an unreadable checkout or provider keeps its marker and names the operator repair above.

Entering a `release_stage` release wait requires a recorded landing or
attested no-change evidence (`GATE_MERGE_UNRECORDED`), and epics refuse `done`
without `merged_at` (`GATE_EPIC_MERGE`). A merge-free definition records no
landing, so the correction surface above remains its repair.

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
4. Invoke `/yoke <skill_id>` and let the target-stage gate references and
   [structural gates](gates.md) govern each move; a crossed segment
   comes back as `skill_handoff`, naming the next skill's command and claim.

A changed effective stage level returns `handoff` with `reason=level_change` and an exact successor launch command; follow the [harness-neutral worker rule](../agents/levels.md#stage-level-handoff) before continuing or retaining a delivery wait.

The registered skills have these behavioral contracts; their source and
target stages always come from the binding:

| Skill id | Segment behavior |
|---|---|
| `refine` | Critique and improve the artifact selected by the pinned policies |
| `shepherd` | Run quality-gated planning for a compatible generated-task policy |
| `implement` | Drive a single implementation lane and its review loop |
| `conduct` | Drive generated task lanes and their integration/review loop |
| `polish` | Perform the definition-bound finishing pass |
| `usher` | Merge and deliver a `release_stage` workflow |
| `dash`, `blitz` | Execute their definition-bound direct-work segments |

Worktree shape also comes from `policies.worktrees` and
`policies.generated_children`. A single-lane
skill keeps implementation and review in one claimed worktree; a
task-graph skill provisions the registered worker/integration lanes; a
`none` policy provisions no lane at all, so the item runs in place under
the session's existing write authority and can live in a project that is
a bare folder with no git repository.

`policies.delivery` of `merge_free` pairs with that: done is the recorded
floor attestation — the agent account plus the observed changes — and no
merge SHA is required or expected.

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

## Routing And Explicit Staffing

The pinned workflow binding selects the skill for an item's live stage. Steering owns staffing; the shared scheduler computes the runnable frontier. The canonical sources are:

- [charge-frontier.md](../strategy/charge-frontier.md) — frontier computation, status-to-adapter mapping, ranking
- `yoke_core.domain.scheduler_routing` — the `next_step` function that turns a status into a command
- `yoke_core.domain.session_launch_mandate` — resolves assigned item routes from pinned workflow bindings

Agents reading the lifecycle should treat those files plus the item's pinned
definition as authoritative for "which command runs next?" The tables here
describe skill behavior and shared stage meaning; they do not define an
item's stage graph.


## Related

- [Lifecycle](lifecycle.md)
