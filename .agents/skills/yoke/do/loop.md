# /yoke do — Bounded Chaining Loop

This file contains the loop logic for `/yoke do`. It is read and executed by the main SKILL.md.

## Constants

- `max_chain_steps` — returned by `yoke sessions identity` from machine config (default: 3). Read once in Step A and reused for all chain decisions.
- Chainable actions: `resume`, `charge` (as indicated by the `chainable` field in the response).

## Loop Procedure

Execute the following loop, starting at `step = 1`:

### Step A: Call the Decision Engine

Read your session identity once per `/yoke do` invocation and reuse the
printed values for the whole run.

Run `yoke sessions identity` as a single foreground call:

```bash
yoke sessions identity
```

It resolves the calling session ambiently and returns the stored identity
the authority holds:

- `session_id` — the resolved session id
- `executor` / `executor_display_name` — canonical harness id and its surface alias
- `provider`, `model` — as registration recorded them
- `execution_lane` and `lane_allowed_paths` — the lane the project's
  session-routing policy assigned this executor, and the downstream paths
  that lane may execute
- `workspace`, `project_id`, `project_slug`, `actor_id`, `actor_label`
- `max_chain_steps` — the chain budget (default `3`)

Every value comes from the authority, so none is advisory and none needs a
label. The call takes no arguments: it resolves ambiently, on both
transports, and works from any session at any time — not only inside this
loop. A refusal names its recovery; a session that cannot reach its own
identity says so rather than inventing one, so never fall back to a locally
detected executor, lane, or model.

**Do not carry identity into later calls.** Shell variables set in one Bash
tool call do not survive to the next, and that is not a problem to work
around here: every session call resolves the caller ambiently, so there is
nothing to carry. Do not prefix commands with `YOKE_SESSION_ID=...` and do
not pass `--session-id`. Passing identity is not harmless duplication — a
value the client guessed *overrides* correct server state. Two Cursor
sessions in one checkout, same harness and same project, reached opposite
outcomes purely on this: the one whose shell variables were empty was routed
correctly, and the one that substituted its locally guessed lane had all 13
frontier items filtered behind a lane its project declares no paths for.
`--session-id` remains only as the operator-debug override the project rules
describe.

Then run the registered `yoke sessions offer` wrapper to get a `NextAction`.
The shared offer path emits canonical `HarnessSessionOffered` and
`NextActionChosen` events internally — the loop does not emit these events
directly.

The session MUST already be active before calling `yoke sessions offer`
(registered by the harness hooks at session start). The offer path validates,
heartbeats, schedules, and claims — it does NOT create sessions.

```bash
yoke sessions offer --step "{step}"
```

That is the whole command. Executor, provider, workspace, and model are read
server-side from the session row, and the lane comes from the row too. The
surface does still accept `--lane` and `--project`, but neither belongs here:
`--lane` is a deliberate operator re-route, and a loop that fills it in is
precisely how a locally guessed lane reached the server. Add nothing else.

Parse the JSON from stdout **in the prompt context** — do not capture it into a shell variable (`_offer=$(...)`) and do not pipe it to a parser (`| python3 -c ...`); the harness renders the command's stdout to the next turn and you read it inline. Bare invocation + prompt-context parsing is the canonical shape, the same as `yoke sessions ownership-guard` at `loop-routing.md` Step B. The response has this shape:

```json
{
 "action": "resume|charge|feed|strategize|wait|escalate",
 "reason": "Human-readable explanation",
 "chainable": true|false,
 "correlation_id": "session-id",
 "context": { ... }
}
```

If stdout is empty or is not a parseable NextAction JSON object —
including an exec that exits 0 with empty stdout — do **not** treat that
as no-work and do **not** release claims. A slow offer can finish
server-side after the harness drops the process; empty stdout is not an
answer. The session id is already in hand. Read durable state before
concluding:

```bash
yoke events query --event-name HarnessSessionOffered --session {SESSION_ID} --limit 1 --json
yoke events query --event-name FrontierStepSelected --session {SESSION_ID} --limit 1 --json
yoke events query --event-name WorkClaimed --session {SESSION_ID} --limit 1 --json
yoke events query --event-name NextActionChosen --session {SESSION_ID} --limit 1 --json
```

Substitute the literal `session_id` captured from `yoke sessions identity`.
`--session` filters `events.session_id`; it is a query predicate, not caller
identity.

- If `HarnessSessionOffered` fired (and `FrontierStepSelected` /
  `WorkClaimed` when the offer selected work), the offer succeeded.
  Recover the NextAction from the latest `NextActionChosen` row's
  `envelope.context`: `action`, `reason`, `chainable`, and
  `correlation_id` are the directive; the remaining context keys are the
  offer `context`. Continue at Step B. Do not release the claim this
  offer already took.
- If those events did not fire, the offer never persisted. Only then
  treat the empty response as a true empty frontier.

If the command exits non-zero **and** stdout is a parseable error **and**
the durable-state check above found no matching offer events, report the
error and stop.

**Note:** Canonical `HarnessSessionOffered` and `NextActionChosen` events are emitted by the shared offer path (via `yoke sessions offer` / the `/v1/sessions/offer` API endpoint), not by this loop. Pass the current `{step}` number to that shared path so it can attach the same loop iteration to both events while centrally handling indexed `item_id` / `task_num` population and merged action-specific context.

### Step B: Route to Mode Handler

Read [`loop-routing.md`](loop-routing.md) for the full routing rules, heartbeat management, checkpoint persistence, and all action-specific handlers (`resume`, `charge`, `escalate`, `feed`, `strategize`, `wait`).

### Step C: Chain Decision

Read [`loop-followups.md`](loop-followups.md) for the chain decision logic, session cleanup (Step D), and error handling.
