# Client control-plane route inventory

Agent operations select their connection through registered Yoke functions.
HTTPS clients send authenticated requests; the serving engine owns SQL.
Local universes dispatch through that same registry in process. A Python
module importing a database helper is evidence to trace, not a defect alone.

## Reachability and corrections

| Reachable site | Previous database reach | Current owner and evidence |
| --- | --- | --- |
| Conduct entry gates | `check_hard_blocks.main` parsed the item and opened a local connection before a lane existed | `yoke advance preflight hard-blocks` calls existing `advance.preflight.hard_blocks`; unchanged `evaluate_blockers` owns every satisfaction and gate filter. |
| Conduct manual reflection capture | `reflection_capture` CLI called its DB writer locally | `ouroboros.reflection.capture` runs the complete parser, persistence and marker pipeline on the server. The client sends the full response file or stdin with explicit project and ambient session. |
| Claude role hook frontmatter, including PM/Designer sidecars | PostToolUse/Failure called `observe.main`; PM/Designer also called `observe_pre.main`. Both connect directly through `observe_db` | Every role uses the shared hook composer and `yoke hook evaluate`; registry chains retain role attribution and run DB policies on the server. Tool grants remain role-owned. |
| Usher optional merge audit | `merge_audit_report.generate_report` queried items, tasks, lanes and simulations on the client; string item parsing also queried locally | `merge.audit.snapshot` returns project-scoped facts through registered dispatch. Local report composition retains branch, dirty-state and conflict checks. Public refs resolve server-side. |
| Guard refusal recoveries | Shell-transform, runtime-import, direct-HTTP and DB-rule denials taught direct dispatcher/HTTP calls or database module mutations | Their shared messages now teach registered scoped reads, additive transforms, lifecycle transitions and Progress Log adapters; missing adapters route to the control-plane operator. Detection and authorization rules stay unchanged. |

The obsolete blocker and reflection module front doors refuse before opening
a database and teach their public command. They are not aliases. New capture
and merge-snapshot functions declare `minimum_serving_version=next-release`;
an older server requires the control-plane operator to serve their carrying
release. Do not switch to a database profile to work around that floor.

Reflection receipts preserve block classifications, parsed/persisted/duplicate
counts and errors. A partial parse, invalid marker or failed persistence is
an incomplete result with recovery, never success. Recognized marker requests
carry the capturing session, project, role and deterministic request identity.
Repeating the same entry does not mint a different field-note request.
Telemetry remains best-effort; the returned receipt does not depend on events.

## Inspected boundaries and exclusions

The discovery roots are `.agents/skills`, `runtime/agents`, `runtime/harness`,
`docs/public`, packet recipe seeds (`schema_api_context_commands_*`), and
client packages (`yoke_cli`, `yoke_harness`). Follow module recipes through
their writers and connection factories. The packaged install tree and harness
adapters are generated outputs; update their canonical sources and regenerate.
Archives describe history and are not live command instructions.

| Boundary | Classification and exact evidence |
| --- | --- |
| CLI registry and adapter dispatch | `commands/registry.py`, its family registries, `_helpers.dispatch_and_emit`, and `transport/dispatcher.py`: connection selection precedes `_call_local`; HTTPS adapters do not load local handlers. |
| Dynamic engine imports | `runtime/api/dynamic_authority_import_allowlist.py` and its `_cli` roster enumerate every declared client-to-engine import. `test_installer_package_boundaries.py` checks live call-site parity. These include local diagnostics, credential custody, source-dev/admin and embedded-engine activation; classifications are not blanket DB exemptions. |
| Direct CLI connection calls | `pulumi_stack_config_loader.py` selects authenticated download endpoints before local materialization. `config_actor_binding.py` uses `local_connection_or_none` and refuses HTTPS because the bearer already binds the actor. `adapters/dev.py` prewarm is explicit source-dev administration. |
| Client-local import families | Board render/timing, readiness observations, Doctor local checks, scratch paths, lane trees, browser/Test Machine execution and GitHub monitoring retain local files/process/credential ownership. Their durable control-plane reads/writes use registered dispatch. Board's optional timing connection is disabled by `remote_control_plane_active`. |
| Installation and universe boot | `project_install/transport.py`, `engine_upgrade_convergence.py`, local setup/import/export/demo/UI and self-host commands are declared engine activation or attended custody operations. SQL here serves or initializes the machine's own universe, rather than bypassing a remote one. |
| Worktree preparation | `worktree_preflight_steps.py` relays item reads, work claims and activation. `worktree_create_db.py` selects hosted authority before local SQL; `worktree_create.py` resolves project identity over transport. Bare interpreter preparation teaching has its separate registered preparation owner. |
| Advance, merge, Usher reconciliation and Resync | Advance preflight relays gates; merge preparation resolves item context via registered reads. `usher_reconcile_github.py` relays durable state. Resync detection/prefetch and epic-task repair helpers use `call_dispatcher`; their imported `connect` re-export is not a live client call. |
| Watchers and QA | Watchers launch the transport-aware command; the candidate source/environment owner stays local. QA runtime SQL belongs to server handlers or deliberately bound test/rehearsal databases. Epic-task domain QA and sessions lookup module recipes are explicitly operator/debug surfaces. |
| Hook runners across harnesses | `yoke_cli` hook adapter selects HTTPS or local entry. `yoke_contracts.hook_runner.policy_home` gives each chain policy one home; `yoke_harness.hooks.local_subset` runs the client-home policies and `yoke_harness.hooks.client_facts` collects the client facts server-run policies read. Claude, Codex and Cursor use these shared handlers. |
| Automatic Agent reflection hook | The registered PostToolUse Agent chain already evaluates on the server; it calls the same capture pipeline with the original hook session. Manual capture serves returns lacking that matcher; no evidence establishes lost automatic reflections. |
| SubagentStop | `agent_stop_chains.py` is a local Git safety net. Its event emitter uses the existing best-effort event boundary; its legacy file-token guard is not a control-plane SQL route. This audit does not replace the safety net with a session-ending hook. |
| Local settings and source helpers | `runtime_settings.py` reads machine config; `classify_dirty_files.py` reads Git and machine checkout mapping; `persist_system_simulation.py` writes a local report; `step_runners.py` uses transport-aware GitHub state/auth. They do not need new control-plane functions. |
| Retained engine/debug front doors | `db_router`, `service_client`, `sessions_cli`, `context_routing`, token minting and schema/retention helpers remain server or explicit operator/debug internals. Product teaching uses registered commands; these internals do not grant an agent direct DB authority. |
| Admin and diagnostic authority | Diagnostic `yoke db read`, governed migration/rehearsal, boot convergence, attended row repair and paired db-admin self-release remain deliberate authority. No credential construction, guard bypass or deployment-run creation belongs in this correction. |

No required correction identified here belongs to Platform. Generic function
transport remains unchanged; the added functions are Yoke engine capabilities.

## Verification homes

`runtime/api/cli/test_agent_control_plane_routes.py` exercises HTTPS envelopes
without local Postgres configuration and refuses local engine dispatch.
`runtime/api/test_agent_control_plane_http.py` joins the adapters to real
authenticated HTTP handlers. Handler, parser, marker, blocker and merge-audit
suites verify durable results, failure details and local-mode composition.
Existing package-boundary and hook-rendering checks cover generated call sites.

These are source proofs. Installed public-route proof belongs to independent
post-deploy Command QA on the exact carrying candidate, using isolated mutation
fixtures. A grep count or a source test alone is not deployed acceptance.

The deployed probe matches the runner's HTTPS origin with the active API
connection's origin. Organization-scoped API paths remain intact for CLI
authorization and routing; they are not part of the server origin comparison.
Different hosts, ports, non-HTTPS URLs and malformed origins refuse before calls.
The probe takes project and member identity from the QA runner, avoiding a
full item-detail read just to discover the already bound project.
