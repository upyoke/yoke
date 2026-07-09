# /yoke do — Loop Routing Rules

Extracted from `loop.md`. Contains Step B (route to mode handler) with all action-specific dispatch logic.
### Step B: Route to Mode Handler

Based on the `action` field, execute the appropriate handler.

Step B emits two separate Bash calls before dispatching the handler:
the pre-dispatch checkpoint, then the handler itself. Splitting the
checkpoint from the handler keeps each statement on its own so the
lint's wrapping classifier evaluates them independently. The keepalive
background loop has been eliminated; the PreToolUse
heartbeat hook refreshes activity at agent turn boundaries and events
are the canonical liveness signal. `YOKE_SESSION_ID` is in the
environment from Step A; the session wrappers resolve it internally.

**Call 1 — pre-dispatch checkpoint.** Single statement: write
the current loop frame to the DB before any compaction risk so Step C
can recover from durable state if context compacts during a long
handler. Run it plain — the lint refuses shell choreography
(`2>/dev/null || true`, pipes, capture) around registry-covered
adapters; the checkpoint is best-effort, so the loop continues even if
the harness surfaces a non-zero exit:

```bash
yoke sessions checkpoint --step "{step}" --action "{action}" --chainable "{chainable}" --item-id "{_item_id}" --status "{_status}" --required-path "{_required_path}" --pre-status "{_pre_status}" --outcome "pre-dispatch"
```

`{_pre_status}` is the offer-time status from Step A's response — `context.status` for `resume`, or `context.scheduler.status` for `charge`. Capture it at the same point as `{_status}` and reuse it on both the pre-dispatch and post-handler checkpoint calls. The post-handler `--status` records where the handler landed (`$_post_status`); `--pre-status` records where it started. Together they let the decision engine measure direct progress (`pre_status != status`) rather than guessing from same-state heuristics.

After the mode handler returns, classify the handler outcome and
persist a post-handler chain checkpoint. The checkpoint records
handler outcome so Step C can consult durable state rather than
prompt-local variables.

**Classify handler outcome:** Immediately after the handler returns,
determine the post-handler outcome before
writing the checkpoint. Use `completed` as the default. Resolve
`{_item_id}` from the Step A response's context: for `resume` use
`context.item_id`, for `charge` use `context.selected_item`, for other
actions use empty string. Also persist `{_status}` (from
`context.status`) and `{_required_path}` (from `context.required_path`
for `resume`, or the scheduler `next_step` mapped to `advance` /
`polish` / etc. for `charge`) when available — these fields enable
no-progress resume detection. When `charge` dispatches from
`context.scheduler.next_step`, also retain that value as `{_next_step}`
for the outcome classifier below.

For routed advance work, re-read the item status after the handler
returns and use the canonical classifier so an internal implementation
slice is not misreported as a completed chain step:

```bash
_handler_outcome="completed"
_post_status="{_status}"
if [ -n "{_item_id}" ]; then
 _live_status=$(yoke items get "{_item_id}" status 2>/dev/null || true)
 if [ -n "$_live_status" ]; then
  _post_status="$_live_status"
 fi
fi

if [ "{_required_path}" = "advance" ] || [ "{_next_step}" = "advance" ]; then
 _handler_outcome=$(python3 -c 'from yoke_core.domain.sessions_handler_outcome import classify_advance_outcome; print(classify_advance_outcome(pre_status="{_status}", post_status="'"$_post_status"'"))')
fi
```

If the routed handler reports an advance-entry substrate failure before
useful implementation work begins, classify `CLASS` with
`classify_substrate_failure`. Only recoverable classes call the helper;
blocked classes set `_checkpoint_chainable=false`. The helper appends
skip memory, releases the claim, and emits `SchedulerOfferSkipped`; the
agent still writes the checkpoint below.

```bash
_handler_outcome=$(python3 -c 'from yoke_core.domain.sessions_handler_outcome import classify_substrate_failure; print(classify_substrate_failure("CLASS"))')
if [ "$_handler_outcome" = "recoverable_substrate" ]; then
 yoke lifecycle skip record-recoverable-substrate {_item_id} \
  --chain-step {step} --project {project} --routed-action {action} \
  --failure-class CLASS --remediation-owner YOK-N
elif [ "$_handler_outcome" = "blocked" ]; then
 _checkpoint_chainable=false
fi
```

Substrate taxonomy (`SUBSTRATE_FAILURE_TAXONOMY` /
`classify_substrate_failure`; unknowns route to `blocked`; starter
classes are theoretical, +11h window produced zero recurrences):

| `failure_class`                   | Outcome                 | Rationale |
|---                                |---                      |---|
| `dirty-tracked-main`              | `recoverable_substrate` | Operator can clean main and retry. |
| `unbound-worktree`                | `recoverable_substrate` | Guard drift is transient after workspace binding refreshes. |
| `path-claim-overlap-incompatible` | `blocked`               | Needs an authored coordination decision. |
| `lease-conflict`                  | `recoverable_substrate` | Lease release makes retry plausible. |
| _anything else_                   | `blocked`               | Unknown classes stop for operator review. |

**Persist chain checkpoint:** Write a checkpoint with the classified
outcome:

```bash
# YOKE_SESSION_ID is in the environment — the wrapper resolves it internally
yoke sessions checkpoint \
 --step "{step}" \
 --action "{action}" \
 --chainable "${_checkpoint_chainable:-{chainable}}" \
 --item-id "{_item_id}" \
 --status "$_post_status" \
 --required-path "{_required_path}" \
 --pre-status "{_pre_status}" \
 --outcome "$_handler_outcome"
```

If the handler provisioned a new worktree (`items.worktree` (branch slug) set,
path claims activated), persist the checkpoint with the classified
outcome and continue chain evaluation as normal. Worktree creation does
NOT terminate the loop — the same harness session keeps the work-claim
and proceeds into worktree-bound implementation/review work in the same
chain run. The session's authority over the new worktree is its
work-claim, validated per tool call by `lint_session_cwd`.

**Completion re-anchor:** After a chainable handler returns, render
the canonical handler-outcome label and emit a short re-anchor block so
Step C operates on bounded output instead of the full raw handler
transcript:

```bash
_chain_label=$(python3 -c 'from yoke_core.domain.sessions_handler_outcome import render_chain_summary_label; print(render_chain_summary_label("'"$_handler_outcome"'"))')
```

For the normal completed outcome, retain the familiar completed-step
header:

```
═══ CHAIN STEP {step}/{MAX_CHAIN_STEPS} COMPLETE ═══
Action: {action} | Item: {_item_id} | Chainable: {chainable}
Returning to /yoke do loop for chain decision.
═══════════════════════════════════════════════════
```

For any non-completed label, render the outcome without the `CHAIN STEP
COMPLETE` wording:

```
═══ CHAIN HANDLER OUTCOME {step}/{MAX_CHAIN_STEPS} ═══
Outcome: {_chain_label}
Action: {action} | Item: {_item_id} | Chainable: {chainable}
Returning to /yoke do loop for chain decision.
═══════════════════════════════════════════════════
```


#### `resume`
Print the claimed work information from `context`:
```
RESUME: Continuing work on {item_id}
Status: {status}
Required path: {required_path}
Reason: {reason}
```
If `context` contains `epic_id` and `task_num`, print this instead of the item line above:
```
RESUME: Continuing work on epic YOK-{epic_id} task #{task_num}
Status: {status}
Required path: {required_path}
Reason: {reason}
```

**Runtime ownership guard.** Before dispatching, confirm this session still owns the item OR the routed-ownership defense still names us as prior owner. Read-only — never releases a claim. Run the guard as its own foreground command with no command substitution, redirection, or shell capture choreography:

```bash
yoke sessions ownership-guard --item "$_item_id"
```

Parse the JSON from stdout in the prompt context. If the command fails, the JSON is unparseable, or `owned` is not `true`, write a non-chainable checkpoint and stop this handler:

```bash
yoke sessions checkpoint --step "{step}" --action "resume" --chainable false --item-id "$_item_id" --outcome blocked
```

Then print `OWNERSHIP LOST: item $_item_id now held by session '<holder_session_id>'. Step C records failure_reason=ownership_lost.`, set `_handler_outcome=blocked`, skip the dispatch below, and fall through to Step C. Do NOT release a claim this session no longer owns.

Then **dispatch using the claimed work context:**

**Epic task detection (first priority):** If `context` contains `epic_id` and `task_num` (epic task work), invoke `/yoke conduct YOK-{epic_id}`. Skip the `required_path` dispatch below.

**Core contract dispatch (all other resume work):** Dispatch from `context.required_path`:

- If `required_path` is `refine`, invoke `/yoke refine {item_id}`.
- If `required_path` is `shepherd`, invoke `/yoke shepherd {item_id}`.
- If `required_path` is `conduct`, invoke `/yoke conduct {item_id}`.
- If `required_path` is `advance`, invoke `/yoke advance {item_id} implementation`.
- If `required_path` is `polish`, invoke `/yoke polish {item_id}`.
- If `required_path` is `usher`, invoke `/yoke usher {item_id}`.

**Contract failure:** If `context.required_path` is not present, print the following and **stop the loop** (call Step D for session cleanup before stopping):
```
CONTRACT ERROR: resume context missing required_path for {item_id}. The core decision engine must provide routing metadata. Check that the API service is running the latest version.
```

**Refine-entry metadata repair is part of this handler, not a new chain step.**
When `required_path` is `refine` and the routed `/yoke refine {item_id}`
auto-fixes a stale File Budget line count via
`yoke_core.domain.idea_readiness_repair` (see
[`.agents/skills/yoke/refine/readiness-repair.md`](../refine/readiness-repair.md)),
the work claim stays held across the repair, the same routed handler
continues to its lifecycle boundary, and Step C records the normal
`completed` outcome — there is no separate chain step for the repair
itself. Releasing the claim or re-offering between repair and the rest
of refine would burn the chain step for paperwork only; refine never
releases for repair-only.

#### `charge`
Print the frontier summary from `context`:
```
CHARGE: {reason}
Runnable items: {runnable_items list}
Selected: {selected_item}
```

Then **dispatch from the scheduler's computed next step.** The selected step is available in `context.scheduler.next_step`:

- If `next_step` is `refine`, invoke `/yoke refine {selected_item}`.
- If `next_step` is `shepherd`, invoke `/yoke shepherd {selected_item}`.
- If `next_step` is `conduct`, invoke `/yoke conduct {selected_item}`.
- If `next_step` is `advance`, invoke `/yoke advance {selected_item} implementation` (issue main-session implementation).
- If `next_step` is `polish`, invoke `/yoke polish {selected_item}`.
- If `next_step` is `usher`, invoke `/yoke usher {selected_item}`.

**Contract failure:** If `context.scheduler.next_step` is not present, print the following and **stop the loop** (call Step D for session cleanup before stopping):
```
CONTRACT ERROR: charge context missing scheduler.next_step for {selected_item}. The core decision engine must provide routing metadata. Check that the API service is running the latest version.
```

**Freshness note (dispatch-side defense for offer-time `items.status` drift; symmetric for `#### resume` above).** The decision engine runs a freshness check inside `decide_charge_action` / `decide_resume_action`. When live `items.status` has advanced past the schedule snapshot AND the recomputed `next_step` is still serviceable by this session's lane/supported_paths, the engine **rewrites** `context.scheduler` (or resume `context.required_path` + `context.status`) in place, sets `context.scheduler.freshness_refreshed=true`, and emits `SchedulerOfferSkipped` with `extra.outcome="refreshed_in_place"`. The agent dispatches against the rewritten next_step without burning a chain step. When the recomputed `next_step` cannot be served, the engine releases the work claim with `offer-stale-after-claim`, appends a chain skip entry, emits `SchedulerOfferSkipped` with `extra.outcome="released_for_handoff"`, and the offer returns `WAIT` with `context.wait_reason="stale_lifecycle_dispatch"` instead of CHARGE/RESUME. Recovery: `yoke events query --event-name SchedulerOfferSkipped --since "1 hour ago"` and inspect `extra.detection_phase`, `extra.outcome`, `from_status`, `to_status`.

#### `escalate`
Print the escalation information:
```
ESCALATE: {reason}
```

**Render the lane-filtered signal first when present.** If `context.lane_filtered_count > 0`, print the note and filtered-item details before blocker guidance so the operator sees the lane situation even when other blockers are also present:
```
{context.lane_filtered_note}
Filtered items ({context.lane_filtered_count}):
 - {item.item_id} ({item.status}): needs /yoke {item.required_path} — claim_state={item.claim_state}
 - ...
```

If `context.blocked_items` is present and non-empty, print:
```
Blocked items: {blocked_items list}
```

If `context.blocked_details` is present and non-empty, render per-blocker explanations instead of
generic blockage text. For each entry in `blocked_details`:
```
 {item_id} blocked by {blocking_item} at {gate_point} gate
 Condition: {satisfaction}
 Rationale: {rationale}
 Status: {reason}
```

If `context.intrinsic_blocked_reasons` is present and non-empty, render per-item intrinsic reasons
after any `blocked_details` block. Intrinsic reasons cover operator-set blocks, legacy
`status='blocked'` drift, idea-incomplete title-only rows, and routed-ownership defense. For each
entry in `intrinsic_blocked_reasons`:
```
Per-item reasons:
 {item_id} ({status}):
   - {reason 1}
   - {reason 2}
```

If BOTH `blocked_details` and `intrinsic_blocked_reasons` are absent or empty, fall back to generic
intervention guidance:
```
Human intervention required. Review blocked items with:
 /yoke doctor
```

If `context.exceptional_items` is present and non-empty, also print:
```
Failed items requiring attention: {exceptional_items list}
```

This action is NOT chainable. Stop the loop.

#### `feed`
Print the feed context from the decision engine response:
```
FEED: {reason}
Blocked items: {blocked_count}
```

**Render the lane-filtered signal first when present.** If `context.lane_filtered_count > 0`, print the note and filtered-item details BEFORE invoking the feed handler so the operator sees that previously-materialized work exists but is lane-incompatible:
```
{context.lane_filtered_note}
Filtered items ({context.lane_filtered_count}):
 - {item.item_id} ({item.status}): needs /yoke {item.required_path} — claim_state={item.claim_state}
 - ...
```

Then read `.agents/skills/yoke/feed/SKILL.md` (resolve relative to the workspace root) and follow its instructions inline. Keep the decision-engine `context` visible as the rationale for why feed was chosen; the feed flow runs its full materialization sequence.

After the feed flow completes, **stop the loop** -- this action is NOT chainable.

#### `strategize`
See [`loop-routing-strategize.md`](loop-routing-strategize.md) — extracted to keep this file under the 350-line cap.

#### `wait`
Print the wait header:
```
WAIT: {reason}
```

**Lane-filtered branch.** If `context.wait_reason == "no_lane_compatible_work"`, the frontier has work but none of it is compatible with this lane. Render the lane situation instead of the generic idle text — the truly-empty wording below is reserved for the truly-empty branch.

```
This lane ({context.actual_lane}) has no compatible work right now.
{context.lane_filtered_note}
Filtered items ({context.lane_filtered_count}):
 - {item.item_id} ({item.status}): needs /yoke {item.required_path} — claim_state={item.claim_state}
 - ...
Paths blocked for this lane:
 - /yoke {entry.required_path} ({entry.count})
 - ...
Options:
 (a) Switch to a harness whose configured lane covers these paths.
 (b) Run the required step manually in this session (e.g. /yoke refine YOK-N).
 (c) Run /yoke feed to materialize additional lane-compatible work, if any exists.
```

**Disabled-process suppressed branch.** If `context.wait_reason == "process_suppressed_no_alternative"`, the decision engine recommended a process-backed action (`feed` or `strategize`) but `do_process_offer_<process>=false` disables it (through the project `session-routing` capability, or machine config only when no project policy resolved — `context.config_source` names which) AND no runnable items exist on the frontier. The recommendation surfaces as informational context — render the suppressed process plus the direct command and config knob so the operator can act:

```
{suppressed.process_key} recommended but disabled by {suppressed.config_key}=false; no alternative work on the frontier.
Run {suppressed.direct_command} directly to materialize work, or flip {suppressed.config_key}=true in machine config.
```

`{suppressed}` is `context.suppressed_process_recommendation`. The `original_reason` and `original_context` fields are available for debugging output if the operator wants the full engine trace.

**Truly-empty branch.** Otherwise, print the generic idle text:
```
No actionable work exists on the frontier. Check back later.
```

This action is NOT chainable. Stop the loop.
