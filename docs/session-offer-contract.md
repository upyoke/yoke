# Session-Offer Contract

> Authoritative specification for the `/yoke do` session-offer request/response
> envelope, identity model, event shapes, and correlation semantics.

Version: 3.3.0
Status: Active

---

## Table of Contents

- [1. Overview](#1-overview)
- [2. Request Envelope: SessionOffer](#2-request-envelope-sessionoffer)
- [3. Response Envelope: NextAction](#3-response-envelope-nextaction)
- [4. Identity Model and Correlation](#4-identity-model-and-correlation)
- [5. Event Shapes](#5-event-shapes)
- [6. Action-Specific Context Payloads](#6-action-specific-context-payloads)
- [7. Adapter Implementation Guide](#7-adapter-implementation-guide)

---

## 1. Overview

A harness session (CLI, API, or future worker) offers itself to Yoke by
constructing a `SessionOffer` and sending it to the core. The core evaluates
the offer against the current backlog state, active sessions, and routing
policy, then returns a `NextAction` directive telling the session what to do.

The contract is defined as Pydantic models in `runtime/api/domain/session.py`.
This document describes the same shapes in prose for adapter authors who do not
want to read the Python source directly.

**Source of truth:** `runtime/api/domain/session.py`

---

## 2. Request Envelope: SessionOffer

A session constructs a `SessionOffer` to identify itself and declare what it
can do.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `session_id` | string | Yes | -- | Globally unique session identifier. Stable for the session lifetime. Used as the correlation key for heartbeat, claim/lease, and ledger events. |
| `executor` | string | Yes | -- | Harness identity (input). Surface-specific values are accepted as input — `claude-desktop`, `claude-vscode`, `claude-cli`, `codex-desktop`, `codex-vscode`, `codex-cli`, composed as `{family}-{surface}` from the runtime entrypoint signal (`CLAUDE_CODE_ENTRYPOINT` for Claude, the Codex env-probe chain for Codex). The coarse family values `claude-code` and `codex` are accepted as fallbacks when no surface signal is available. Yoke canonicalizes the value at write time via `runtime.harness.hook_helpers_identity.canonical_harness_id` so `harness_sessions.executor` stores only `claude-code` or `codex`; the surface-specific input is preserved in `harness_sessions.executor_display_name` and surfaced as the operator-facing executor in board / session rendering. `HarnessSessionOffered` / `HarnessSessionStarted` event envelopes and the offer envelope's `context.executor` field carry the canonical value; the surface-specific alias rides along as `context.executor_display_name` when known. Code that branches on family must use the `is_codex()` / `is_claude()` predicates from `runtime.harness.hook_helpers`, never raw equality against the coarse strings. |
| `provider` | string | Yes | -- | Model provider (e.g., `anthropic`, `openai`). |
| `model` | string | Yes | -- | Model identifier string (e.g., `claude-opus-4-7`). |
| `capabilities` | list[string] | No | `[]` | Capability tags the session supports. Free-form strings; known values include `browser`, `shell`, `file_write`, `github`. |
| `workspace` | string | Yes | -- | Absolute path or identifier for the working directory/repo the session operates in. |
| `execution_lane` | string | No | `"primary"` | Execution lane identity. The canonical lane tokens are `DARIUS` and `ALTMAN`; path eligibility is defined only by `lane_paths_<lane>` policy, not by scheduler output. For project sessions, Yoke core resolves the default lane from the project's DB-backed `session-routing` capability via `yoke_core.api.routing_config.RoutingConfig.default_lane_for_executor()`, which walks the chain: exact key (`executor_default_lane_claude_vscode`) -> wildcard key with the longest non-wildcard prefix (`executor_default_lane_claude*`) -> global `executor_default_lane_unknown` -> hardcoded `primary` sentinel. Machine config is only the no-project/operator fallback. Skill wrappers MUST call the routing-config helper instead of hand-passing free-form strings into `offer_session()`. |
| `offered_at` | string (ISO 8601) | No | Current UTC time | Timestamp of when the offer was created. |
| `supported_paths` | list[string] | No | `[]` | Canonical downstream path names this session can execute (e.g., `["advance", "shepherd"]`). The two Yoke-owned harness families today — Claude and Codex — no longer declare this field; Yoke core derives the effective list server-side from the shared Yoke registry plus any limitations in the coarse harness manifest. Surface-specific executor values normalize back to the family manifest (`codex-desktop` -> `runtime/harness/codex/manifest.json`, `claude-vscode` -> `runtime/harness/claude-code/manifest.json`), and registry-derived truth overrides any caller-supplied list. Manifest presence is the single axis of explicit limitation: `codex` ships `runtime/harness/codex/manifest.json`, `claude-code` has no manifest and therefore falls into the backward-compat branch below. See **Path Derivation Mapping** for details. |

### Path Derivation Mapping

The decision engine derives the required downstream path from `scheduler_context.next_step`:

| `next_step` value | Required path |
|-------------------|---------------|
| `refine` | `refine` |
| `shepherd` | `shepherd` |
| `conduct` | `conduct` |
| `advance` | `advance` |
| `polish` | `polish` |
| `usher` | `usher` |

Process-backed actions (`feed`, `strategize`, `doctor`) are first-class lane-policy tokens in addition to the lifecycle paths above. The mapping is registered in `yoke_core.domain.work_processes.process_key_to_path`:

| Process key | Required path |
|-------------|---------------|
| `STRATEGIZE` | `strategize` |
| `FEED` | `feed` |
| `DOCTOR` | `doctor` |

`DOCTOR` is recognized as a vocabulary token even though the decision engine does not yet emit a `DOCTOR` `NextAction` — operators may pre-declare it in `lane_paths_*` so future autonomy lands without a config change.

### Lane policy and `do_process_offer_*` compose as AND

For lifecycle-path actions (`charge`, `resume`), the decision engine consults the lane allowlist in the queries layer and again in `decide_charge_action` / `decide_resume_action`. For process-backed actions (`feed`, `strategize`, future), `apply_process_offer_gate` evaluates the `do_process_offer_*` policy before the lane allowlist. The two gates compose as an AND:

| `lane_paths_<lane>` contains the path | `do_process_offer_<process>` | Result |
|---|---|---|
| Yes | `true` | Action passes through (FEED/STRATEGIZE) |
| Yes | `false` | CHARGE-swap (when runnable items present) or suppressed-WAIT with `wait_reason="process_suppressed_no_alternative"` naming `do_process_offer_*` |
| No | `true` | `wait` with `wait_reason="lane_policy_disallows_path"` |
| No | `false` | Policy wins: CHARGE-swap (when runnable items present) or suppressed-WAIT naming `do_process_offer_*` |
| Lane has no allowlist (default) | any | Existing policy-only behavior (backward-compatible) |

**Gate ordering: policy first for process actions.** When both gates would block, the policy branch wins because `do_process_offer_*=false` is the load-bearing cause: switching lanes cannot enable a disabled process. Lane WAIT fires only when the policy enables the process but the current lane excludes the path. Lane WAIT does *not* record disabled-process skip memory; that signal stays specific to `do_process_offer_*=false` blocks.

### Per-project Offer Stance: `session-routing`

The `do_process_offer_*` family is project policy. Once an offer resolves to a
project, the project's DB-backed `session-routing` capability is the complete
authority:

1. `session-routing.process_offers.<process>`
2. `session-routing.process_offers.default`
3. off (autonomy is opt-in)

Machine config is only the no-project fallback. Gate rewrites and
`SchedulerOfferSkipped` events carry `config_key` (always the actionable
per-process key) plus `config_source` (the project capability or `machine
config`) so the operator flips the setting that actually changes the outcome.
Loader: `routing_config.load_process_offer_policy(..., project_settings=...)`.

**No terminal ESCALATE from the policy branch.** A disabled process never surfaces as a terminal `escalate` whose only cause is the config flag. When no runnable items exist, the policy branch returns a non-chainable `wait` carrying `context.suppressed_process_recommendation` (process key, config key, direct command, original reason / context). The operator sees the recommendation as informational context and can run the direct command directly or flip the config flag.

When the effective `supported_paths` list is non-empty (either caller-declared or Yoke-core-derived) and the derived path is **not** in the list, the engine returns `escalate` with:
- `context.escalate_reason`: `"unsupported_path"`
- `context.required_path`: the path the item needs
- `context.supported_paths`: the effective paths (Yoke-core-derived for supported harnesses)

When the effective `supported_paths` list is empty because no manifest exists for the executor and the caller did not provide explicit paths, all downstream paths are considered supported and no validation occurs. This preserves backward compatibility. Today only `codex` ships a manifest under `runtime/harness/codex/manifest.json`; `claude-code` has no manifest and therefore falls into this backward-compat branch. A manifest does not copy command/path truth; it only confirms the shared registry source and declares explicit disabled paths when the substrate cannot support them.

When lane policy (not manifest capability) filters every runnable frontier item and no blockers remain, the engine returns `wait` with:
- `context.wait_reason`: `"no_lane_compatible_work"`
- `context.actual_lane`: the offering session's lane
- `context.lane_filtered_count`: the number of items filtered by lane policy
- `context.lane_filtered_note`: an operator-facing explanation of the lane situation
- `context.lane_filtered_items`: structured per-item details (see section 6 `wait`)
- `context.lane_filtered_paths`: a compact `(required_path, count)` view derived from the filtered items

Unlike `unsupported_path` (an `escalate` reason that describes a harness capability gap for a specific item), the filtered-empty lane case is a normal WAIT outcome — the system is not broken, the lane is simply waiting for compatible work or for the operator to switch harness/lane. The loop's `wait` branch renders this context first so the operator sees which paths are blocked for the current lane instead of the generic "no work on the frontier" idle text. Blocker-driven `escalate` and `unsupported_path` `escalate` retain precedence — see priority order below.

### Example

```json
{
 "session_id": "sess-d4f7a2b1-9c3e",
 "executor": "claude-desktop",
 "provider": "anthropic",
 "model": "claude-opus-4-7",
 "capabilities": ["browser", "shell", "file_write", "github"],
 "workspace": "/Users/bee/yoke",
 "execution_lane": "DARIUS",
 "offered_at": "2026-03-31T12:00:00Z",
 "supported_paths": ["shepherd", "advance"]
}
```

---

## 3. Response Envelope: NextAction

The core returns a `NextAction` telling the session what to do next.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `action` | enum string | Yes | -- | One of six canonical values: `resume`, `charge`, `feed`, `strategize`, `wait`, `escalate`. |
| `reason` | string | Yes | -- | Human-readable explanation of why this action was chosen. |
| `chainable` | bool | No | `false` | True when the loop may immediately re-offer after this action completes. |
| `correlation_id` | string | Yes | -- | Links back to `SessionOffer.session_id`. |
| `context` | dict or null | No | `null` | Action-specific payload. Keys depend on the `action` value -- see section 6. |

### Action Kind Definitions

| Value | Meaning | Chainable |
|-------|---------|-----------|
| `resume` | Continue work on an existing in-progress item the session was previously working on. | Yes |
| `charge` | Pick up a new item from the frontier and begin work. The `context.scheduler` field carries type-aware next-step routing (`refine`, `shepherd`, `conduct`, `polish`, `usher`). | Yes |
| `feed` | Materialize new work from the Strategic Markdown Layer (SML-to-idea materialization plus frontier-fact refresh). | No |
| `strategize` | Perform guided Strategic Markdown Layer review when the SML is absent, stale, or incoherent. | No |
| `wait` | No actionable work right now; session should wait and re-offer later. | No |
| `escalate` | A situation requires human attention or a different executor. Includes blocked and failed items with specific explanations. | No |

### Priority Order

The decision engine evaluates in this fixed priority order:

1. **resume** — session has an unreleased claim.
2. **charge** — shared scheduler found an assignable step and the SML is coherent.
3. **escalate (blockers)** — blocked or failed items exist with no runnable work.
3b. **wait (no lane-compatible work)** — runnable work exists globally but lane policy filters every candidate for this session; emitted as `wait` with `wait_reason="no_lane_compatible_work"`, not `escalate`.
3c. **feed (graph stale)** — dependency graph is stale, SML coherent and fresh.
4. **feed (no items)** — no materialized frontier work but the SML is coherent and fresh.
5. **strategize** — the SML is absent, stale, or incoherent.
6. **wait** — nothing actionable.

### Shared Scheduler

Both `/yoke do` and `/yoke charge` consume the same shared scheduler
(`runtime/api/domain/scheduler.py`). The scheduler computes a single
project-scoped frontier with:

- Type-aware next-step routing (issue vs epic)
- Dependency / gate evaluation with persisted rationale
- Deterministic candidate ranking
- Claim-state evaluation per item
- Truthful SML coherence (``sml_coherent``)
- Post-delivery drift review — project-scoped review that
 classifies delivered work as ``neither``, ``frontier_only``,
 ``sml_only``, or ``both`` to drive feed/strategize routing
- Per-blocker structured details (``blocked_details``) propagated to
 the escalate action and available on the charge-schedule surface

The session-offer endpoint maps the scheduler result into the `NextAction`
envelope. The charge endpoint exposes the raw scheduler result via
`/v1/charge/schedule`.

### Example

```json
{
 "action": "charge",
 "reason": "Backlog has 3 refined items; YOK-N matches session capabilities.",
 "correlation_id": "sess-d4f7a2b1-9c3e",
 "context": {
 "item_id": "YOK-N",
 "title": "Implement widget API",
 "branch": "YOK-N"
 }
}
```

---

## 4. Identity Model and Correlation

The session identity model is designed to support later claim/lease, heartbeat,
and resume correlation without retroactive schema changes to the offer envelope.

### Key identity fields

- **`session_id`** -- globally unique, stable for the session lifetime. This is
 the primary correlation key across all downstream systems (active-session
 tracking, heartbeat, ledger events, charge records).
- **`executor`** -- the canonical harness identity stored in `harness_sessions.executor` — always `claude-code` or `codex`. The surface-specific input (`claude-desktop`, `codex-vscode`, etc.) is preserved in `harness_sessions.executor_display_name` and used by board / session rendering. Multiple
 sessions may share an executor identity but will have distinct `session_id` values.
- **`execution_lane`** -- execution lane identity. Yoke core resolves the default lane per executor from config, then applies the matching `lane_paths_<lane>` policy before routing.

### Codex runtime correlation

When `executor="codex"` and `CODEX_THREAD_ID` is set, the underlying Codex thread
UUID is also persisted in `harness_sessions.offer_envelope` under the
`runtime_session_id` key. In the current Yoke-owned Codex adapter,
`CODEX_THREAD_ID` is already the canonical `session_id` passed into
`session-offer`; `runtime_session_id` is retained as auxiliary correlation data
for legacy or diagnostic consumers, not as evidence of a second generated
primary ID.

### Correlation flow

```
SessionOffer.session_id ──> NextAction.correlation_id
 ──> HarnessSessionOffered event (context.session_id)
 ──> NextActionChosen event (context.session_id)
 ──> harness_sessions.session_id
 ──> work_claims.session_id (via claim acquisition)
 ──> heartbeat correlation
 ──> offer_envelope.runtime_session_id (Codex only)
```

---

## 5. Event Shapes

The session-offer loop always emits the core lineage events: `HarnessSessionOffered` (offer received), `NextActionChosen` (decision returned), and `ChainStepCompleted` (chain step recorded). It also emits audit/evidence events when it skips stale or blocked candidates, leaves useful chain budget unused, or applies an explicit chain-end override. All conform to the envelope structure documented in `event-contract.md`. Per-event field tables, context fields, and emission points live in [session-offer-contract/event-shapes.md](session-offer-contract/event-shapes.md).

---

## 6. Action-Specific Context Payloads

`NextAction.context` carries action-specific data — `resume`, `charge`, `feed`, `strategize`, `wait`, and `escalate` (with sub-shapes for unsupported-path, blocker-driven, and lane-mismatch escalations). Per-action JSON examples, scheduler.next_step routing, session-shutdown guards (`CHAIN_PENDING`, `ACTIVE_CLAIM`), offer-time claim reconciliation, and the legacy stranded-claim audit query live in [session-offer-contract/action-payloads.md](session-offer-contract/action-payloads.md).

---

## 7. Adapter Implementation Guide

Operator-facing wrappers should expose `/yoke do` and keep any direct
`session-offer` invocation internal to the adapter or skill implementation.

To implement a session-offer adapter:

1. **Construct a `SessionOffer`** with all required fields. For supported
 harnesses such as `claude-code` and `codex`, pass the canonical harness
 session ID from the runtime (`CLAUDE_SESSION_ID`, `CODEX_THREAD_ID`, or the
 equivalent hook payload value) rather than inventing a second format.
 Unsupported/fallback executors may generate their own stable `session_id`.
 Set `executor` and `model` from your runtime context. Declare your
 capabilities honestly. For Yoke-owned harnesses, let the core derive
 `supported_paths` from the shared registry plus manifest limitations instead
 of treating `--supported-paths` as operator input.

2. **Send the offer** to the core (API endpoint, or direct function call for
 CLI adapters).

3. **The core emits `HarnessSessionOffered`** to the execution ledger.

4. **The core evaluates** the offer against backlog state, active sessions, and
 routing policy, then constructs a `NextAction`.

5. **The core emits `NextActionChosen`** to the execution ledger.

6. **Receive the `NextAction`** and branch on `action`:
 - `resume` / `charge`: Start or continue implementation work.
 - `feed` / `strategize`: Invoke the appropriate Yoke command.
 - `wait`: Sleep for the suggested duration, then re-offer.
 - `escalate`: Surface the message to a human or different executor.

7. **Correlate via `session_id`.** Your `SessionOffer.session_id` appears in
 `NextAction.correlation_id` and in both ledger events. Use it for
 heartbeat, claim/lease, and result reporting.
