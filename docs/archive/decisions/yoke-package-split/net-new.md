# Net-new authoring (YOK-1902)

Pieces with no existing code to move. Attach-point anchors verified against the live
tree (Agent D).

## 1. `/v1/db/read` raw-read endpoint + `db.read.run` (AC-36/AC-37)

- **Route** `yoke_core/api/routes/db_read.py` — register like the other routers in
  `app_factory.py:170-195` (`from ...routes.db_read import router as db_read_router;
  v1_router.include_router(db_read_router)`).
- **Handler** `yoke_core/domain/handlers/db_read.py` + registrar following the
  `handlers/_register_events_reads.py:6-15` pattern:
  `registry.register("db.read.run", handle_db_read, DbReadRequest, DbReadResponse,
  side_effects=[], claim_required_kind=None)`, listed in `handlers/__init_register__.py:25-44`.
- **Read-only enforcement** (handler-internal): open a connection under a **read-only
  Postgres role**, `SET statement_timeout`, apply a **row cap** on fetch. Arbitrary
  writes are structurally impossible on this path.
- **Permission gate `db.read.raw`:** add `PERM_DB_READ_RAW = "db.read.raw"` to
  `actor_permissions.py` (constants L21-33) + `PERMISSION_DESCRIPTIONS` (L50); do NOT
  add to `_PROJECT_OWNER_PERMS` (Yoke-internal/operator-only, unscoped). Wire in
  `yoke_function_permissions.py:permission_key_for` (L41-75): `if fid ==
  "db.read.run": return PERM_DB_READ_RAW`. Enforced via
  `actor_permissions.require_permission` → typed `403` for actors lacking it.
- **`yoke db read "SELECT …"` command** (function id `db.read.run`,
  `yoke_cli.commands.db`): transport-aware — relays to `/v1/db/read` against an
  `https` env, runs in-process against a `local-postgres` dev env. The checkout holds
  no prod DB driver/credential. The legacy `db_router query` raw path is likewise
  transport-aware (Tier-C dev-fenced module) and never opens a direct prod
  connection.

## 2. Prod-direct-connection refusal + the net-new prod-flag predicate (AC-16)

- **Attach at the DB-connection layer:** `db_backend.py:188 connect()` +
  `:209 connect_psycopg()`, both funneling `connected_env_readiness.py:190
  connect_with_readiness()`. Insert the refusal at the head, before
  `_open_native_postgres(resolve_pg_dsn())`. Attaching here covers BOTH the
  function-call dispatcher AND the raw `db_router query`/`db read` path.
- **Env classification, NOT DSN host inspection.** The SSH tunnel makes Aurora
  appear as `127.0.0.1`, so host-sniffing cannot distinguish local from tunneled
  prod. Authority is the **prod flag on the connected-env binding**.
- **NET-NEW predicate:** no `is_prod`/`prod_flag` field exists on the connection
  contract today. Add an explicit `prod: bool` flag to the connected-env binding
  (`machine_config.schema` + `yoke_connected_env.load_active` at L89), default
  `false`, true for the `prod`/`cloud-prod` envs. `connect()` consults it: a
  `local-postgres`-transport connection (`POSTGRES_TRANSPORTS={"local-postgres"}`)
  bound to a prod-flagged env raises typed `prod is API-only`; a `local-postgres`
  connection when `yoke_core` is absent raises `local-postgres requires source-dev
  core`. No operator input needed — the spec mandates this classification; the only
  net-new design choice (which attribute marks prod) is settled as an explicit flag.
- **Consequence:** retire the standing `cloud-prod` direct-to-Aurora env as a daily
  driver. The few remaining local-postgres-only-against-prod commands (board rebuild
  — already an https `board.data.get` fetch; long `check-ci --wait`) must work over
  https.

## 3. Cached-read endpoints (Decision 2 / AC-17)

Three core READ functions exposed over the API so the 2 converting guardrails fetch
control-plane state without a direct DB import. Client cache: short TTL, **fail-open
on miss** (PreToolUse stays fast/offline-tolerant).

| Endpoint | Feeds | Underlying read | TTL / failure |
| :-- | :-- | :-- | :-- |
| `claimed_worktrees(session_id)` | `lint_session_cwd` | active `work_claims` → `session_claimed_worktrees.claimed_worktrees` (+ `items.status` for the pre-implementing gate) | short, session-scoped; fail-open |
| `recent_bash_commands(session_id)` | `lint_long_command_polling` | `session_tool_calls` rows for `tool_name IN ('Bash','Monitor')`, `completed_at`, `command_summary` | short; fail-open |
| `active_worktree_items()` + `strategy_docs(project, slugs)` | `lint_main_commit` | `items` (id/title/status/worktree) + `strategy_docs` rows | already via `call_dispatcher` (`items.list.run`); fail-open |

`lint_main_commit` already uses this pattern (the precedent); the two converting
lints adopt it. `session_claimed_worktrees` stays a core module; only the lint logic
moves to `yoke_harness/guardrails/`.

## 4. Local-core Docker/Colima launcher (AC-38..AC-42)

Greenfield `yoke_cli.local_core.{launcher,colima,docker,compose,state}` +
`yoke_cli.commands.core`. Commands: `yoke core install/start/status/logs/stop/
upgrade`. Container assets `yoke_core/docker/{entrypoint.py,healthcheck.py}` +
`packages/yoke-core/Dockerfile`.

Contract:
- **macOS:** prefer Docker-with-Colima — detect `docker`, detect/teach `colima`,
  start Colima when safe, fail with copy-pasteable setup instructions when either is
  missing. **Linux:** Docker daemon directly; fail clearly when absent.
- Own a stable local project name/container-label namespace so status/stop/logs/
  upgrade find the right containers without scanning unrelated Docker state.
- Persist machine-local state under `~/.yoke/local-core` (ports, env name, volume
  names, image tag, compose hash, last health check) — never in project repos.
- Start a local/dev Postgres container + a `yoke-core` API container, run
  migrations from the server/core context, wait for API health, then configure a
  `local-core` env whose `api_url` points at the local API.
- Recovery: `status` distinguishes Docker/Colima-unavailable, Postgres-unhealthy,
  core-unhealthy, migration-in-progress/failed, port-conflict; `logs` surfaces both
  containers; `stop` cleans up containers without deleting volumes; `upgrade`
  refuses while a migration is in progress and reports rollback/retry guidance.
- **Package wall preserved:** the launcher shells out to Docker/Colima and writes
  `~/.yoke/local-core`; it does NOT import `yoke_core`, depend on `psycopg`, or
  open Postgres. Clean-install proof asserts this after `yoke core start`.
- **Reuse:** only the Docker CLI-invocation *idiom* from
  `domain.deploy_core_container*` (which is core remote-deploy and STAYS core); the
  launcher targets a local daemon, not a remote host.

## 5. Boundary enforcement + clean-install proof (AC-10/AC-31/AC-32)

- `tests/import_graph/test_yoke_package_boundaries.py` — static (parse imports, no
  live server): the four allowed edges, every forbidden edge, absence of
  `runtime.api`/`runtime.harness` production imports, and that `yoke-cli`/
  `yoke-harness` wheels contain no `yoke_core` modules.
- `tests/packaging/test_clean_install_cli_harness.py` — install `yoke-cli` +
  `yoke-harness` with the source checkout absent from `PYTHONPATH`; smoke
  `yoke --version`, `yoke status`, image-backed board-art preview, a PreToolUse
  hook fire; assert the product cannot `import psycopg` and a `local-postgres`
  connection fails loudly.
- `tests/packaging/test_local_core_container_launcher.py` — `yoke core start` +
  `yoke core status` (Docker/Colima-mocked in CI); the local-mode leg talks to the
  local `yoke-core` API service, not imported backend modules. Pin the
  transport↔context binding: in-process direct-Postgres dispatch reachable only when
  `yoke-core` is importable.
