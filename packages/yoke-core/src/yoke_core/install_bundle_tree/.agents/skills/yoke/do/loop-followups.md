# /yoke do — Loop Follow-ups

Extracted from `loop.md`. Contains Step C (chain decision), Step D (session cleanup), and error handling.

---

### Step C: Chain Decision

After the mode handler completes and the checkpoint is persisted (Step B),
**re-read the chain checkpoint from the DB** to recover durable state. Do
NOT rely solely on prompt-local `step` and `chainable` — after a long
handler (e.g., shepherd), those values may be lost from context.

```bash
# YOKE_SESSION_ID is in the environment — the wrapper resolves it internally
_checkpoint_json=$(yoke sessions checkpoint-read) || _checkpoint_json="{}"
```

Parse the checkpoint JSON to extract `chainable` and `step`:

```bash
_cp_chainable=$(printf '%s' "$_checkpoint_json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(str(d.get('chainable',False)).lower())")
_cp_step=$(printf '%s' "$_checkpoint_json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('step',0))")
_cp_outcome=$(printf '%s' "$_checkpoint_json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('handler_outcome',''))")
```

Then apply the chain decision using the **persisted** values:

1. If `_cp_outcome` is `interactive_checkpoint`, **stop the loop without Step D**. The process skill owns resume / abort / complete from its checkpoint, and generic cleanup must not release the intentionally-open process claim.
2. If `_cp_chainable` is `false`, **call Step D (session cleanup)** then **stop the loop**. (Worktree-scope entry is no longer a loop terminator — it's an in-session scope transition that continues the chain.)
3. If `_cp_step >= MAX_CHAIN_STEPS` (the value captured from the init block), print:
 ```
 Chain limit reached ({MAX_CHAIN_STEPS} steps). Re-run /yoke do to continue.
 ```
 **Call Step D (session cleanup)** then **stop the loop.**
4. **Outcome-aware step accounting.** Read `_cp_outcome` (the `handler_outcome` field on the checkpoint, owned by `yoke_core.domain.sessions_handler_outcome`). When the outcome is `slice_committed` (routed advance committed an internal slice but the item is still `implementing`) or `recoverable_substrate` (routed handler hit a recoverable advance-entry substrate failure before useful work began), the loop **MUST NOT** bump the useful step counter — set `step` to `_cp_step` and re-enter Step A so the next offer can either resume the same item or skip past it via chain skip memory. For `completed` or any unknown non-terminal outcome, set `step` to `_cp_step + 1` and **go back to Step A** (re-offer to the decision engine). The same canonical Python set is at `yoke_core.domain.sessions_handler_outcome.NON_USEFUL_STEP_OUTCOMES`.

**Fallback:** If `yoke sessions checkpoint-read` returns empty (`{}`) or fails, fall back to
prompt-local `chainable` and `step` values from Step A's original response.
This preserves backward compatibility when the service client is unavailable.

**Ownership-guard failure.** When the runtime ownership guard in
the `resume` dispatch block returns `owned=false`, the loop writes a
non-chainable checkpoint with `handler_outcome=blocked` and sets
`_handler_outcome=blocked` before falling through to Step C. That
failure shape is observable here as a checkpoint with
`handler_outcome=blocked` and the contextual marker
`failure_reason=ownership_lost` (echoed in the loop's stderr line and
recoverable from the `OWNERSHIP LOST` log entry). Step C's chain
decision then runs the standard non-chainable terminal path — call Step
D and stop the loop, never release a claim this session no longer owns.

### Step D: Session Cleanup

**The harness owns session lifetime — the loop does NOT terminate the session itself.** Session lifetime is harness-owned: the `Stop` and `SessionEnd` hooks run the hook-runner cleanup helpers. The agent surface has no business terminating the session — agents that want to surrender their work without terminating the session use the positive primitive:

```bash
yoke claims work release --all-mine
```

This releases every active claim THIS session still holds with canonical reason `agent_handoff_session_scoped`, leaving the session row alive for the harness Stop hook to finalize cleanly. Use it when the loop has reached a clean handoff point and wants to free the work claim explicitly — most chain steps already release through their own routed handler, so calling this is rare.

The PreToolUse lint `lint_no_agent_session_end` refuses agent-dispatched session-shutdown helper invocations; `AGENTS.md` explains the doctrine under "Operational primitives".

**Audit-only context — what the hook path emits.** When the harness Stop / SessionEnd hooks invoke their cleanup helper internally, the aggregate `HarnessSessionEndReleasedClaims` event records each released claim with `context.via="no_flags"`; per-claim `WorkReleased` events fire through the typed release path. The new `--all-mine` primitive emits the same envelope shape with `context.via="agent_handoff_session_scoped"` so downstream audit callers distinguish the two paths.

**Honest checkpointing still matters — it controls how the Stop hook resolves.** When `Stop` / `SessionEnd` fires, the hook runner reads the persisted chain checkpoint and either:

- Closes the session when the checkpoint records `chainable=false` or exhausted budget (`step ≥ max_chain_steps`).
- Defers via `ChainEndDeferred` when `chainable=true` with budget remaining (the next agent turn picks up).

A useful step that leaves budget remaining but the loop wants the harness to clean up next must update the checkpoint to `chainable=false` (the honest signal that no further work is queued) before the harness fires Stop. `YOKE_SESSION_ID` remains stable across loop iterations (set once in Step A) so the same session record receives every checkpoint write.

**Operator-mediated abort with budget remaining** — when a harness-restart / crash-recovery / operator-asserted abort needs to bypass the chain-pending guard on a hook-driven cleanup, the hook runner accepts `--override-chain-end --chain-end-rationale "<why>"` on its internal invocation. The override emits `ChainDeclineOverridden` for audit. This is an operator escape hatch, not an agent shape — the loop never authors it.

The Stop hook (`python3 -m runtime.harness.hook_runner Stop`) takes a different path: it uses the non-destructive idle-cleanup helper (no force, no override). Two cleanup preconditions must hold before the helper closes a session:

- **No claims held** — the active-claim guard. Claimed-but-stale sessions are left alone for the reclaim path.
- **No chain-pending budget** — the chain-pending guard. When the loop has released its work claim mid-chain (`advance/finalize` step 6b's `handoff-to-polish` / `handoff-to-usher`) but the persisted checkpoint still has `chainable=true` and `step < max_chain_steps`, the helper returns `status='chain_pending'`, emits `ChainEndDeferred`, and leaves the session alive. The JSON return carries a `next_action` string — the canonical resume command — so the next agent turn (or an inspecting operator) can resume via `yoke sessions offer` without re-deriving the loop entry shape. The configured stale-heartbeat window (`session_stale_ttl_minutes` in machine config; per-executor overrides via `session_stale_ttl_minutes_<executor>_override`) remains the safety net for genuinely abandoned chains; the next `yoke sessions offer` reclaim path emits `WorkReclaimed` as today.

## Chain Summary Rendering

The end-of-step block ``/yoke do`` prints reads
``handler_outcome`` from the chain checkpoint and renders the
operator-facing label via ``yoke_core.domain.sessions_handler_outcome.render_chain_summary_label``.
The labels distinguish:

- ``handler completed`` — routed handler reached a lifecycle boundary; render `=== CHAIN STEP N/M COMPLETE ===` as today.
- ``implementation slice committed; handler continuing`` — routed advance made an internal commit but the item is still ``implementing``; do NOT render `CHAIN STEP COMPLETE`.
- ``recoverable substrate failure; handler continuing`` — routed handler hit a recoverable advance-entry substrate failure; the chain summary names ``failure_class`` and ``remediation_owner`` from the chain skip memory entry.
- ``interactive checkpoint active`` — an enabled process action reached an operator checkpoint; the work claim is intentionally preserved and the chain is non-chainable.
- ``handler blocked`` — handler hit a real non-recoverable blocker.

## Chain Summary Evidence Binding

`/yoke do` chain summaries are composed by the inline agent at chain end. Two
classes of statement appear in those summaries:

- **Narrative claims** — what the loop attempted, what it decided, what it
  declined. These describe the chain's history and may stay free-form.
- **State claims** — anything that names a DB-resident ticket field for an item
  the chain touched. The item status, worktree, deployed-to, and deployment-flow
  fields — and every other column on the item row (see your ``items`` packet
  stanza) — count as state. So do the matching fields on the epic-task row
  (see your ``epic_tasks`` packet stanza) for touched epic tasks.

**Contract: before composing any state claim about a touched item, re-read the
canonical value with ``yoke items get <YOK-N>
<field>`` in the same turn and quote only what the read returned.** For
epic-task state claims, use the matching canonical router read for the
``(epic_id, task_num)`` row before quoting the value. Free-form narrative about
decisions and intent is allowed; state claims must be evidence-bound.
Pre-handler in-flow variables (``_status``, ``context.status``, the offer's
pre-dispatch checkpoint) are intent, not evidence — they describe what the loop
saw on entry, not what the DB holds at summary time.

This is a tightening of [`AGENTS.md`](../../../../AGENTS.md) ``## Execution
Discipline`` ("Verify after executing"). The execution-discipline rule already
fires at mutation time; chain summaries are the second place state is asserted,
and they are the place where intent-vs-evidence drift is hardest for the
operator to catch — by chain end, the intermediate evidence has been
disposed of.

### Why the contract exists

A side-effecting CLI runs between the chain's intent and the summary. The most
common offender is ``yoke_core.domain.worktree_preflight``, which (as part of
its single-shot worktree-entry sequence) atomically claims work, activates path
claims, creates the worktree branch, and **flips the item's status field to
``implementing``** (see your ``items`` packet stanza). When the agent composes the summary from in-flow variables
captured *before* preflight, the canonical DB has already moved past those
variables. The operator gets a wrong picture of the chain's residual side
effects.

A 2026-05-07 chain run produced this exact failure: chain step 2 dispatched
through ``worktree_preflight`` for an item that began at ``refined-idea``,
preflight flipped the item status field to ``implementing``, the chain exited with
``chainable=false``, and the agent's free-form summary then claimed the item
was "back at ``refined-idea``". The operator's first follow-up was "why is X
now implementing again?" — the canonical state had already been mutated; the
summary was wrong.

This is the chain-summary mirror of `advance/finalize.md`'s `Compact-Resistant
Summary`, which prints `Transition: {_status} → {_target}` from in-flow
variables. Finalize gets away with in-flow values because it composes its
summary inside the same flow that performs the mutation. ``/yoke do`` chain
summaries cannot — the loop summary runs *after* the routed handler returns,
and prompt-local variables may have been compacted away during the handler
run.

### Manual verification scenario

To confirm the contract is doing its job, simulate the failure shape:

1. Begin a chain that enters worktree preflight for an item still at
   ``refined-idea`` — for example, ``/yoke do`` selecting an item at
   ``refined-idea`` whose scheduler ``next_step`` is ``advance``.
2. Let preflight run to completion (so the item status flips to
   ``implementing`` and the worktree row is recorded).
3. Force the chain to exit with ``chainable=false`` (a real blocker, an
   ``escalate``, or chain-budget exhaustion).
4. Immediately before composing the summary prose, run
   ``yoke items get <YOK-N> status`` and
   ``yoke items get <YOK-N> worktree``.
5. Quote those values verbatim in the state claim. The summary must report
   ``implementing`` and the worktree branch — not the pre-preflight
   ``refined-idea`` that lives in the agent's intent memory.

If the summary names a field other than the four common ones above (for
example the deployment-flow field after a reconciliation auto-fill, or
the deployed-to field after ``--env`` — see your ``items`` packet stanza),
apply the same rule: one fresh ``db_router items get`` per named field,
quoted verbatim.

## Live-Claim Recovery: Canonical Holder Lookup

When ``/yoke do`` skips, stops, or summarizes an item because another
live session holds its work claim, the canonical claim facts (``claim_id``,
holder ``session_id``, ``item_id``, ``claim_type``, ``claimed_at``) are
already in the ``SchedulerOfferSkipped`` event payload — the offer
revalidation helper queries the same typed ``work_claims`` schema that
``runtime.harness.harness_sessions_claims.cmd_who_claims`` uses.

**Manual verification command** for an operator confirming the holder
during recovery:

```bash
yoke claims work holder-get YOK-N
# Returns one canonical row: claim_id|session_id|item_id|claim_type|claimed_at
```

Do NOT infer claim state from ``items`` columns or guessed
``work_claims`` columns; the canonical claim schema lives in your
``work_claims`` packet stanza, and obsoleted names such as
``owner_session_id`` / ``claim_session_id`` / ``item_claims`` /
``work_claims.target_id`` do not exist there.

## Error Handling

- If `yoke_core.api.service_client` module is not found, print an error directing the operator to check the API installation.
- If the JSON response cannot be parsed, print the raw output and stop.
- If an unknown `action` value is returned, print a warning with the raw response and stop.
- **On any error exit**, call Step D (session cleanup) before stopping.
