# Carve-out: yoke_cli (YOK-1902)

`yoke_cli` is the installable `yoke` command: UX, machine config/auth,
transport, project-file writers, board-art generation, browser-runtime home, and
the net-new local-core launcher. It imports ONLY `yoke_contracts` + the transport
client; never `yoke_core` / `runtime.api.*` / `psycopg`.

## The transport chokepoint split (the critical hand-edit)

The single place transport is selected is **`call_dispatcher` in
`yoke_cli.transport.dispatcher`**. The HTTPS relay lives separately in
`yoke_cli.transport.https`. It selects:
- `local_only=True` → in-process `dispatch(request)` (client-local renderers:
  `agents.render.*`, `packets.*` — must run where the tree lives).
- else → `resolve_https_connection()`; https present → `relay_https`; else →
  in-process `dispatch(request)` (the local-postgres dev/test leg).

**Implemented split:** the client imports `call_dispatcher` without dragging in
core. The core adapter is now a facade over the client dispatcher, and the
in-process dispatch leg imports core only when selected:
- `yoke_cli.transport.dispatcher` — `build_request`/`build_actor`/`emit_response`
  + the https branch + transport SELECTION + the fail-closed guards. The in-process
  `dispatch` leg becomes a **lazy import** (import inside the function), so a client
  wheel with no `yoke_core` never imports it; on `ImportError` it returns a typed
  error envelope naming the fix — never silently falls through.
- The in-process `dispatch` itself stays core (`yoke_core.domain.yoke_function_dispatch`).

**Fail-closed rules attach here (AC-16):** when the active connection is
`local-postgres` AND the env is **prod-flagged** → typed `prod is API-only` error
(not a `dispatch` call). When `local-postgres` selected AND `yoke_core` absent →
typed `local-postgres requires source-dev core`.
`yoke_cli.transport.https.resolve_https_connection` enforces
"half-configured https fails loud" — extend
that posture to the local-postgres direction.

## Move-map (selected; full per-module table in the Agent B report referenced by the Progress Log)

| Old module | New module | Notes |
| :-- | :-- | :-- |
| `cli.yoke_operations_cli` | `yoke_cli.main` | the `yoke` console entrypoint; two-stage resolution (registry → tool-shaped fallback) |
| `cli.yoke_subcommand_registry` (346) | `yoke_cli.commands.registry` + `.alias_registry` | SPLIT under cap (primary vs alias registry) |
| `cli.yoke_transport` (240) | `yoke_cli.transport.https` | https relay + connection resolve + fail-closed |
| `service_client_structured_api_adapter` (312) | SPLIT → `yoke_cli.transport.dispatcher` (client) + core dispatch leg | see above; **add to File Budget** |
| `service_client_structured_api_adapter_inventory` | `yoke_cli.transport.adapter_inventory` | static `CLI_ADAPTERS` table |
| `service_client_shared_session_resolver` | `yoke_cli.config.session_resolver` | ambient id; no DB despite `service_client_` prefix |
| `cli.yoke_flag_adapters` (+ ~35 family files) | `yoke_cli.commands.flag_adapters` + `commands/adapters/<family>.py` | ALL relay via `call_dispatcher`; zero direct DB (verified) |
| `cli.yoke_flag_adapters_helpers` | `yoke_cli.commands._helpers` | `dispatch_and_emit`, `client_project_context`, field-note footer |
| `cli.yoke_tool_shaped` | `yoke_cli.commands.tool_shaped` | no-function-id helper resolver |
| `cli.yoke_board_art_variant_command` (312) | `yoke_cli.commands.board_art.variant` | local helper (no function id) |
| `cli.yoke_board_art_variant_loop` (285) | `yoke_cli.commands.board_art.loop` | |
| `cli.yoke_board_art_variant_image` (270) | `yoke_cli.commands.board_art.image` | |
| `cli.yoke_git_hook_commands` | `yoke_cli.commands.git_hook` | `AdapterFn` type lives here |
| `cli.yoke_qa_browser_command` | `yoke_cli.commands.qa_browser` | |
| `cli.yoke_hooks_relay` (+ `_identity`) | `yoke_cli.hooks.relay` (+ `relay_identity`) | imports `runtime.harness.hook_*` → coordinate with harness pkg |
| `cli.yoke_cli_manifest` | `yoke_cli.manifest` | pure consumer; schema → contracts |
| `cli.yoke_operation_inventory(+_data)` | `yoke_cli.operation_inventory(+_data)` | |
| `cli.terminal_pager` | `yoke_cli.terminal_pager` | |
| `cli.board_rebuild_output` | `yoke_cli.commands.board_rebuild_output` | client render/pager (board is client-rendered) |
| `domain.machine_config` | `yoke_cli.config.machine_config` | loader; NO DB (verified) |
| `domain.machine_config_writer` / `_status` | `yoke_cli.config.machine_config_writer` / `_status` | |
| `domain.project_install` (+ file-layer siblings) | `yoke_cli.commands.project_install*` | apply/uninstall; consumes server bundle |
| `domain.browser_runtime_home` | `yoke_cli.browser_runtime.home` | + relocate `runtime/browser_runtime/**` package-data |
| `domain.session_ambient_identity` / `session_process_anchors` | `yoke_cli.config.*` | pure ambient id |

## STAYS CORE (dev/test/operator-debug fenced — do NOT ship in the client product)

`board_rebuild_timing_events` (emits events), `db_router*` family (in-process
dispatch tables), `raw_query*` (`db_backend.connect_psycopg`), the
`service_client*` family, `yoke_function_dispatch`, and the in-process `dispatch`
leg of the adapter. The CLI reaches these only by **relaying a function-call
envelope** — today's flag adapters already do exactly this (zero direct
`service_client_*` mutation imports).

## Terminal-safe command preservation (both classes — AC-43/AC-44)

Wired in `yoke_operations_cli.main` (L238-247) via two-stage resolution (registry
first, `resolve_tool_shaped` fallback on `KeyError`):

1. **No-function-id local helpers** — grouped in `--help` under namespace `[family]`
   with `-> client-local helper (no function id)` (L86-90). Families:
   `yoke_board_art_variant_command`, `yoke_git_hook_commands`,
   `yoke_qa_browser_command`. The **net-new `yoke core ...` lifecycle joins this
   class** (greenfield tool-shaped namespace group).
2. **`ambient_session_required=False` function commands** — normal registry entries
   dispatched via `call_dispatcher`; terminal-safe because the *handler* (core) sets
   the flag. Examples: `strategy.doc.create`/`strategy.ingest`/`strategy.seed_defaults`,
   `ouroboros.field_note.append`/`.list`/`.get`. The CLI never inspects the flag — it
   relays; the server permits the terminal session.

**Invariant to preserve:** the two-stage resolution order; the namespace-grouped
`--help` distinguishing the two classes; the field-note footer on every `--help`.
`resolve_tool_shaped` + `SUBCOMMAND_REGISTRY` move together into `yoke_cli`; the
`ambient_session_required` flag stays a handler property in core.

## Auth / secret backend (3-way)

No dedicated secret-store module exists today. Secret resolution splits:
- **reference shape** (`credential_source` kinds `token_file`/`dsn_file`/`env`/
  `aws_secrets_manager`, `SECRETS_DIR_NAME`) → contracts (`machine_config.schema`).
- **client token-file read** → `yoke_cli.auth.secret_store` (from
  `yoke_transport._resolve_token`).
- **DSN/AWS resolution** → core (`db_backend`).
`auth_context.py`/`auth_schema.py` are server-side org/actor auth (core), unrelated
to the CLI machine credential.

## checkout→project resolver

`machine_config_contract_projects.project_entry_for_checkout` (→ contracts) +
`machine_config.project_id` (→ cli). `worktree_paths` (308 lines, imports
`machine_config`) participates in repo-root resolution — **review for DB authority
before placing** (client repo-root resolution vs core worktree mechanics; likely
split).

## local-core launcher — greenfield (NET-NEW; see net-new.md)

Confirmed greenfield: no existing module does local Docker/Colima/compose
orchestration for a client substrate. The only reuse is the Docker CLI-invocation
*idiom* from `domain.deploy_core_container*` (which is core remote-deploy and STAYS
core). `install_yoke_launcher_claude` (tools/) is a cli candidate — confirm.
