# Yoke Function Call Reference

Registered function ids are the typed control-plane interface. Use their
`yoke <subcommand>` adapters; Git, gh and external tools remain command-shaped.
Read the operation's `--help` for payload, target, authorization and recovery.
The dispatcher verifies claims before the canonical domain handler executes.
Live startup recipes: `yoke packets render --role main_agent`; request a topic
with `--detail full` for its complete schema and recipes.

## Operation families

Each registered id has one catalog owner:

| Work | Catalog |
|---|---|
| Work/path/coordination claims and decisions | [Claims](functions-claims.md) |
| Items, sections, progress, readiness and lifecycle | [Items](functions-items.md) |
| Projects, settings, strategy, Packs and environments | [Project configuration](functions-project-configuration.md) |
| QA cases, evidence and test machines | [QA](functions-qa.md) |
| Sessions, actors, deployment, messaging and live services | [Runtime](functions-runtime.md) |
| Generated tasks, dispatch and reviews | [Tasks](functions-tasks.md) |
| Pinned definitions, canon updates and routing | [Workflows](functions-workflows.md) |
| Lane preparation, landing, merge and close-out | [Worktrees](functions-worktrees.md) |

## Envelope

Models: `yoke_contracts.api.function_call`. Client item selectors are complete
public refs; the serving engine alone resolves internal item keys. Task targets
also carry `task_num`. Other record ids retain their own domain meaning.

```json
{"function":"<registered id>","version":"v1","request_id":"<uuid>",
 "actor":{"session_id":"<session>"},
 "target":{"kind":"item","public_ref":"PREFIX-N"},
 "payload":{},"preconditions":{},"options":{}}
```

Responses carry `success`, `function`, `version`, `request_id`, `result`,
`warnings[]`, one optional `error` (`code`, `message`, `jsonpath`,
`recovery_hint`) and `event_ids[]`. Consume typed fields. Primary mutation
failure and downstream-degraded warnings are different outcomes; inspect both.
Post-write verification marked degraded is partial-state evidence, never green.

## Claim verification

| Catalog value | Dispatcher obligation |
|---|---|
| `none` | No work-claim check; handler/project/org authorization still applies. |
| `item` | Active target item claim belongs to calling session. |
| `epic` | Calling session holds the target task's parent item claim. |
| `qa_subject` | Verify the case's item/run/project subject and recording authority. |
| `self_only` | Target claim belongs to calling session. |
| `steering` | Require a live steering seat covering the target project/document; refusal names `steering_seat_required`, seat acquisition or `yoke say --steering`. |

These six values come from `yoke_core.domain.yoke_function_registry`; `none`
means Python `None`. Claim policy never grants project/org permissions.

## Identity, replay and rollout

Use a stable request id for one intended write. Same function/id replays its
ledger response; cross-function reuse refuses. After ledger expiry a call is new.
Never repeat a mutation merely to request `--json`; request its receipt initially.
Mutations remain committed when a separately reported downstream side effect
degrades. Required operational facts belong to durable owners, not event history.

The registry owns ids, request schemas, handler/claim metadata, adapter status
and minimum serving versions. New ids declare their serving floor; below-floor
calls refuse with a served recovery or operator escalation. Clients tolerate
absent optional response fields from older builds without inventing selectors.
HTTP dispatch/health remain cross-version infrastructure boundaries; agents use
registered adapters. `internal` adapter status grants no access by itself.

Source maintainers enumerate the catalog with
`yoke_core.domain.handlers.__init_register__.register_all_handlers` and
`yoke_core.domain.yoke_function_registry.list_entries`; request schemas come
from `schema_for`. The source Atlas renderer is
`python3 -m yoke_core.tools.atlas_render_docs render`.
See [DB reference](../db-reference.md) for domain contracts and the CLI entrypoint.
