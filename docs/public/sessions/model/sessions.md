# Session and work-claim model

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Sessions](../index.md) > Session model
<!-- /yoke:breadcrumbs -->

Schemas and ownership rules for harness sessions and work claims. Read [timestamp discipline](../../databases/migrations.md#timestamp-discipline) for timestamp conventions.

The additive `session_state` projection is defined in the
[session state glossary](../../guide/glossary.md).

## Table: harness_sessions

`yoke universe prune --dry-run` previews disposable completed detail and
settled agent-only message graphs; it preserves session identity, unresolved
work and every human-involved message. See [retention](../../universe-retention.md).

Session end stamps, process presence and work ownership are independent.
Active work claims protect their holders regardless of activity age or process
presence. Explicit release, completion, cancellation or authorized termination
settles ownership; automatic reclaim refuses with `reason=active_work_claim`.

The roster consumes `session_state.status`, `active_at` and `reason`.
Status is Working for an open live tool call, or a running/unknown unfinished
turn whose newest sign of life is within `session_idle_minutes` (default 20).
Waiting covers every other non-ended session, including finished turns.
`ended_at` or `terminated_at` makes it Ended. Native process death never changes
this display status. `active_at` is the latest of `last_tool_call_at`,
`last_heartbeat`, `turn_posture_at` and `native_turn_end_recorded_at`.

The same projection drives CLI, Sessions, Frontier and Machines; callers supply
the project idle setting and open tool-call facts. `sessions list --status`
filters before pagination. `sessions get SESSION-ID --full` and the card's (i)
retain presence, activity, intent, custody, next actor and timestamps as detail.
Older responses lacking the display fields require a server upgrade and refresh.

Steering reports, fleet-delta alarms, message liveness, reclaim, the `liveness`
field, last-tool ages in labels and raw reasons in explicit CLI Frontier/item JSON and named-field reads keep
their existing separate rules. The server's reclaimable
flags match `liveness=stale`. `classify_activity` applies holdings and progress rules;
execution rechecks protection before mutation.
Wake routing uses `activity_liveness` for hook reachability: a fresh heartbeat
may keep hooks reachable while tool activity is silent, but never hides a
recorded native process death.


See [reclaim and current calls](reclaim.md) for terminal custody and in-flight rules.

**Long commands and sparse tool boundaries.** Registered Command cases and watcher-backed suites refresh the owning session and claims while the child runs. The persisted work claim protects a silent or crashed holder until explicit release or terminal action.

```sql
session_id TEXT PRIMARY KEY -- globally unique session ID (from contract)
launch_origin TEXT NOT NULL DEFAULT 'operator' -- yoke after launch binding; gates native wake
executor TEXT NOT NULL -- executor identity (e.g., claude-code, codex)
provider TEXT NOT NULL -- model provider (e.g., anthropic, openai)
model TEXT -- provider-attested served model; NULL until attested and landed
reasoning_effort TEXT -- served effort, distinct from requested_reasoning_effort
context_window_tokens INTEGER -- served window, distinct from requested_context_window_tokens
usage_totals TEXT -- measured usage document; parse through session_usage_facts
execution_level TEXT NOT NULL DEFAULT 'primary' -- session grouping identity stamped by session-routing settings
capabilities TEXT DEFAULT '[]' -- JSON array of capability tags
project_id INTEGER REFERENCES projects(id) -- registered project; NULL outside any project
org_id INTEGER REFERENCES organizations(id) -- authority org; set only outside any project
workspace TEXT NOT NULL -- absolute path to working directory
mode TEXT DEFAULT 'wait' -- wait (not parked) or parked; scheduling posture only, never authority
offered_at TEXT NOT NULL -- ISO 8601 when session was registered
last_heartbeat TEXT NOT NULL -- ISO 8601 of last heartbeat
native_process_gone_at TEXT -- when the death was first seen, not when last reported
native_process_gone_evidence TEXT -- bounded JSON evidence from local records
ended_at TEXT -- NULL while open; set when session ends
offer_envelope TEXT -- checkpoint and skip-memory telemetry JSON (optional)
actor_id INTEGER -- registered acting identity; legacy/additive storage permits NULL
```

**Session scope.** CHECK `harness_sessions_scope_exactly_one` requires exactly one of `project_id` and `org_id`. `session_message_recipients`, `session_termination_reaps` and `session_evidence_fetches` carry the same pair and exactly-one check, so a recipient, reap or evidence fetch for a session outside any project is owned by its org. Registration resolves the org from the authenticated authority and actor membership, never from the working directory, and the stored scope never changes; existing project rows keep `org_id` NULL.

**Actor binding.** Hand-started sessions bind their operator. Launched sessions inherit the launching actor transitively through `requester_actor_id` at authenticated registration; this outranks OS login and relay bearer identity. An unreadable launch refuses registration. Actions on another session write a `SessionActionPerformed` row into the TARGET session's history carrying the ACTING actor, and is role-checked against the target project (for a session outside any project, its own actor or that org's role) by `yoke_core.domain.session_action_authority`: project membership for messaging, waking, holding alive, and terminating a launched worker; operator-driven sessions refuse termination and name claim release as recovery. Contract: `docs/archive/decisions/session-actor-follows-the-person.md`.

The process-gone columns record machine evidence without ending a claim holder. The reporting machine keeps its record until the control plane ends the session, so a retained session is reported again every poll; the stamp is the native's own exit time where the machine read one (correcting an earlier report's guess), else the time this session's first report about that same process earned, and a report about a different, older process is dropped whole rather than overwriting newer evidence, so later activity can still supersede it. `sessions.list.native_process` exposes the observation until a later tool call supersedes it, and drops it when the evidence measured `exit_code` 0 under a session that declared a wait — parked, turn_posture waiting whose `turn_posture_at` is present and not before the current `episode_started_at`, or holding an item armed in the merge queue — because a finished headless command is that wait rather than a disappearance; a non-zero exit and an exit nobody measured still read as gone. `sessions.list.native_process_exited_at` keeps that unsuperseded exit's time even when a declared wait explains it, so a reader asking whether any process is running still sees a parked session's clean exit. The `offer_envelope` column retains checkpoint and skip-memory telemetry.

**Turn ends and project refusals.** A relayed Stop or SessionEnd still records waiting posture for an existing session owned by the authenticated actor when checkout project authorization denies the request. The refusal retains its project restrictions and performs no registration or cleanup. A policy Stop hold asking the agent to continue does not stamp waiting. Codex CLI's relay also reads the newest clean or failed `task_complete` from the rollout tail; later prompts or tool calls invalidate it, and an older observation cannot overwrite a newer running posture. Waiting permits native resume only for Yoke-origin sessions with native surface authority. If a posture write fails, the hook refusal names the failure and recovery alongside the project refusal; restore checkout authorization and retry through `yoke hook evaluate`.

**Chain checkpoint:** The checkpoint API persists handler outcome and work identity for recovery and telemetry. Terminal closeout consumes a matching checkpoint. Checkpoint budget does not block session ending; idle cleanup preserves active claims, document locks, keepalive holds, and pending launch or wake delivery. Read through `yoke sessions checkpoint-read`.

**Probe sessions are audit rows.** A probe has ended within `PROBE_MAX_LIFETIME_SECONDS` (30) of `offered_at`, has `tool_call_count = 0`, and has no `first_user_prompt_at` stamp. The stamp is written on the session row at the prompt boundary. Probe rows remain in `harness_sessions` for audit; operator-facing session lists and steering counts exclude them through the shared `session_probe` predicate. Live sessions are never classified as probes.

Indexes: `idx_harness_sessions_level(execution_level)`, `idx_harness_sessions_heartbeat(last_heartbeat)`.

Inspect with `yoke sessions list`; see [chat titles](../session-titles.md).

**Launch binding.** The hook binds the exact session through launch attestation;
folder and time proximity prove nothing. Relay reports preserve binding and receipt.
Assigned workers must claim their item before the deadline or fail as
`launch_work_claim_missing`, freeing staffing. An original worker may recover
an uncontested timeout; see [late acceptance](../../agents/level-launches.md#delayed-launch-workers).
Itemless workers only acknowledge.
Death before work fails as `abandoned_without_claim`, even before acknowledgement,
and notifies the requester. Inspect binding, phase, exit code and stderr before
retrying: `yoke session-control launch get LAUNCH-ID --json`.

## Table: work_claims

Tracks active harness-session occupancy through one canonical target pair: `target_kind` names the target vocabulary and `scope` stores the exact kind-specific JSON object. Claims with `released_at IS NULL` are active.

- **Item** (`target_kind='item'`): `scope={"item_id":N}`.
- **Epic task** (`target_kind='epic_task'`): `scope={"epic_id":N,"task_num":N}`.
- **Process** (`target_kind='process'`): `scope={"process_key":K,"conflict_group":G}`. STRATEGIZE and FEED share `strategy-control-plane:<project>` and therefore conflict.
- **Steering** (`target_kind='steering'`): `scope={"project_id":N}` or `{"project_id":N,"document":SLUG}`; N identifies the document's owning project for a document seat. Distinct non-overlapping document seats may coexist. Paired locks remain in `strategy_doc_claims` through `steering_claim_id`.

Domain validation requires each kind's keys and permits steering's optional document key. Storage has no specialized target, typed-owner, or registration-provenance columns.

```sql
id INTEGER PRIMARY KEY
session_id TEXT NOT NULL -- FK to harness_sessions.session_id
target_kind TEXT NOT NULL -- item|epic_task|process|steering|migration_serialization|qa_admission|route_qualification (deploy_serialization: retired, release by id)
scope TEXT NOT NULL -- canonical JSON object; exact shape is validated by target_kind
claim_type TEXT NOT NULL DEFAULT 'exclusive' CHECK(claim_type='exclusive')
claimed_at TEXT NOT NULL
last_heartbeat TEXT NOT NULL
released_at TEXT
release_reason TEXT -- completed, released, reclaimed, handed_off, expired, session_ended
reason TEXT -- verbatim acquisition rationale
reason_intent TEXT -- canonical acquisition intent
release_reason_intent TEXT -- caller's release intent
```

Indexes: `idx_work_claims_session(session_id)`, `idx_work_claims_session_released(session_id, released_at)`, and `idx_work_claims_heartbeat(last_heartbeat)`.

Active-claim exclusivity invariants — these partial unique indexes, each scoped to `released_at IS NULL` so historical released overlap rows remain queryable evidence:

- `idx_work_claims_active_item ON work_claims(scope) WHERE released_at IS NULL AND target_kind='item'`.
- `idx_work_claims_active_epic_task ON work_claims(scope) WHERE released_at IS NULL AND target_kind='epic_task'`.
- `idx_work_claims_active_process_conflict` indexes `scope.conflict_group` where the process claim is active.
- `idx_work_claims_active_steering ON work_claims(scope) WHERE released_at IS NULL AND target_kind='steering'`.

Item and epic-task partial unique indexes prevent concurrent connections from leaving two unreleased claims on one work unit. `claim_work` retains `WHERE NOT EXISTS` for readable holder lookups. A losing writer raises `SessionError("ALREADY_CLAIMED")`, naming the winning session id.

A steering seat covers a scope, not a project. Its `scope` is `{"project_id": N}` for a whole project, or `{"project_id": N, "document": "SLUG"}` for one strategy document owned by that project. Two seats coexist unless their scopes overlap: two documents in one project are two seats, while a project seat overlaps only CURRENT-PLAN document steering of that project. A refusal names the holder's actor, machine, and session, and points at both `yoke claims steering list --project P --active-only` and taking a seat on a different document. Steering is therefore the one kind whose exclusivity is not an index — two overlapping scopes are different JSON objects, so no unique index on `scope` can reject the pair. Its storage-level layer is the `SELECT ... FOR UPDATE` on the project row that `acquire` takes before it evaluates overlap, which serializes every steering acquire in one project; the index on `scope` remains as the narrower guarantee that one exact scope has one live row. A project seat covers its unlinked items and CURRENT-PLAN members, excluding other document-linked items even without a live document seat; a document seat covers items linked to that exact owning-project/document identity in `item_strategy_docs`, including items executing in other projects — the link `strategy.execution.link` writes, and the one `items.create` writes when intake names a `strategy_doc`. Membership is read live, so a link written after a message was sent still decides which seat the message is now the business of. The fleet report for a document seat lists only its items; delivery-plane and machine facts (unregistered launches, launchable surfaces, plan limits) stay project-wide because delivery and machine capacity are shared by every seat. Steering acquisition locks the project row, then creates the seat and, for a document seat, that document's lock in one transaction. A document conflict rolls back the seat. A project-wide seat may lock a standing plan with `--plan-doc`; without that flag it locks no document. Releasing one seat releases only its paired document lock, even when the session holds another seat in the same project. Steering release and stale-session reclamation release each pair together, while direct release of the paired document is refused until the seat leaves.

Shell access: item/process targets use `yoke claims work`; steering uses `yoke claims steering acquire --project P [--doc SLUG | --plan-doc SLUG] [--reason TEXT]` (`--doc` narrows the seat to that document's linked items; `--plan-doc` locks the standing plan while the seat covers the whole project; neither flag covers the project and locks nothing), `list [--project P] [--active-only]` (which names each seat's scope, holder actor, and machine), and `release CLAIM_ID --reason TEXT`. All dispatch through `/v1/functions/call`. `claims.steering.list` answers for one project, so a caller asking which seats exist across every project it can see reads `sessions.steering_groups.list` (`yoke sessions steering-groups list`): no inputs, one row per live seat, carrying the seat's session id under the same `steering_group_session_id` name the session roster spells it on every row that seat covers. Visibility is deliberately the OR the roster applies, because a session steers a project it did not start in — a seat is visible when the project it steers is visible, or when the session holding it lives in a visible project. `yoke_core.domain.sessions_steering_groups_read.live_steering_group_session_ids` is the read, over the same `steering_scope_coverage.live_steering_claims` rule the roster's own projection uses, so a released claim and an ended holder are seats in neither. The app's card tint ranks groups by sorted seat id; this read avoids fetching the complete roster twice per mount.

### Steering fleet report

What a steering session cannot see from inside its own turn: available work, quiet claim holders, and four failures that arrive as silence, composed server-side and appended to the messages that session already receives. See [Steering report](../steering-report.md).

### Live claim-holder lookup

The canonical recipe for "which session currently holds the work claim on `PREFIX-N`?" is the registered read (function id `claims.work.holder_get`):

```sh
yoke claims work holder-get PREFIX-N
```

It returns the active `work_claims` row (`released_at IS NULL`) — `claim_id`, holder `session_id`, `target_kind`, `scope`, `claimed_at`, and `last_heartbeat` — in one call. Item lookup matches `target_kind='item'` plus canonical `scope={"item_id":N}`; do not query removed specialized or owner columns. The same recipe is the canonical example in the generated agent context packet (`yoke_core.domain.schema_api_context`, topic `claims`).

Inside the Yoke source repo only, the in-tree `python3 -m yoke_core.hooks.sessions_cli who-claims <item-id>` helper additionally joins the owning `harness_sessions` row (surfacing `executor` and `mode`) and accepts `--current-episode`. That module is not importable from an installed Yoke, so it is an operator/debug recipe for this repo, never a portable one.

`work_claims` is the **active session occupancy** primitive — including which session currently steers a project or strategy-doc scope. It is NOT path/file ownership truth (that lives in `path_claims`) and NOT a dangerous shared-operation lock (those are the [shared-operation coordination claims](coordination.md#shared-operation-coordination-claims)). Process path claims attribute back to their owning process work-claim through `path_claims.owner_work_claim_id`.

## Related
- [Shared coordination](coordination.md)
- [Path claims](path-claims.md)
- [QA model](../../verification/model/qa.md)
Unregistered failures leave the report after item completion, a later registered launch, or operator settlement. Exit evidence renders as `native_exited`; see [launch recovery](../../agents/level-launches.md#unregistered-launch-failures).
