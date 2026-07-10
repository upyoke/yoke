# Yoke Package Split — Authoritative Move-Map (YOK-1902, Slice 0)

This directory is the **published Slice 0 artifact** for YOK-1902 (Hard-cut Yoke
package split for installable CLI). It is the HARD GATE: it substitutes for the
Architect/Simulator review the mega-issue forgoes, and **nothing moves in Phase 1
until this lands**. It was produced by a parallel read-only fan-out (4 analysis
agents, one per concern) verified against the live tree on `main` at YOK-1902
branch point (commit `911d0b75c`).

## Files

- `README.md` — this file: organizing principle, the four packages, Decision 1/2
  resolutions, slice execution order, green-boundary strategy, risks, spec
  corrections.
- `codemod-rules.md` — the ordered prefix-rule table + the exact-match exception
  set (the frozen rules the scripted bulk rewrite consumes).
- `carve-out-contracts.md` — every module moving to `yoke_contracts`, with
  consolidations and oversized-file split plans.
- `carve-out-cli.md` — every module moving to `yoke_cli`, the transport
  chokepoint split, the dev-fenced core exceptions inside `cli/`.
- `carve-out-harness.md` — the verified Decision-1 harness split (client/core/
  contracts) + the function-level boundaries of the 11 SPLIT files + Decision-2
  guardrails (16 lints).
- `net-new.md` — net-new authoring: `/v1/db/read` + `db.read.run`, the prod-flag
  predicate + connect-layer refusal, the 3 cached-read endpoints, the local-core
  Docker/Colima launcher.

## The organizing principle — cut along authority, not function

A module's package is decided by **where it runs and whether it holds Postgres
control-plane authority**, never by what it is "about":

- **Authority-bearing → `yoke_core` (server only).** Anything that mutates or
  reads shared state through a DB connection, emits events, or mutates
  claims/sessions. This is the **default sink**: ~1,400 of ~2,895 source modules.
- **Client-side, zero-authority → `yoke_cli` / `yoke_harness`.** UX, machine
  config/auth, transport, local file writers, agent-runtime adapters, fast local
  guardrails. They reach authority only by relaying a function-call envelope.
- **Shared wire/file shapes → `yoke_contracts`.** The piece that lets client and
  server agree on types without the client importing the server.

The census that anchors this (non-test source modules): `domain` 888, `engines`
181, `domain/handlers` 79, `tools` 60, `board` 43, `routes` 20,
`harness`+`hook_runner` 49, top-level `service_client*`/`api` ~82. Carve-outs
leaving core total ~40 modules (contracts ~20, cli ~12, harness is a near-even
client/authority split).

## The four packages (final internal layout)

```
packages/
  yoke-contracts/src/yoke_contracts/
    api/            function_call, cli_manifest, install_bundle, install_manifest
    project_contract/ board_art/{config,render_seed,variants,variants_image,
                        image_to_emoji,image_geometry,palette,_data,data/*.txt},
                      scaffolds
    machine_config/ schema
    hook_runner/    types, remote_policy, chain_registry, hook_ordering
    codex/          codex_model, codex_hooks_model
    hook_helpers_model, hook_helpers_identity, field_note_text
  yoke-cli/src/yoke_cli/
    main, manifest, operation_inventory[_data], terminal_pager
    transport/      https, dispatcher, adapter_inventory
    config/         machine_config[_writer,_status], session_resolver,
                    session_ambient_identity, checkout_context
    auth/           secret_store (token-file resolution)
    hooks/          relay, relay_identity
    browser_runtime/ home  (+ relocated runtime/browser_runtime/** package-data)
    local_core/     launcher, colima, docker, compose, state         (NET-NEW)
    commands/       registry, alias_registry, tool_shaped, flag_adapters, _helpers,
                    adapters/<family>.py, board_art/{variant,loop,image},
                    project_install*, git_hook, qa_browser, core (NET-NEW), db
  yoke-harness/src/yoke_harness/
    claude/         adapter, merge_settings
    codex/          adapter, codex_entry, codex_open_app, codex_hooks_payload,
                    codex_db_resolution
    hook_runner/    runner, typed_dispatch, identity, deadline, mode_gate,
                    decision_render, adapter_capability, capability_resolve,
                    run_tail, subprocess_policy, session_workspace, target,
                    session_lifecycle_client, session_dispatch, remote_entry,
                    telemetry, denial, stdin, service_client,
                    hook_runner_register, + the codex/first-prompt dispatchers
    guardrails/     the 16 PreToolUse lints (see carve-out-harness.md)
    bootstrap, hook_helpers*, hook_helpers_session_id, hook_helpers_heartbeat
  yoke-core/src/yoke_core/
    api/            app_factory, server_entrypoint, http_auth, observability*,
                    routes/* (flat, + NET-NEW db_read), service_client* (family)
    domain/         ALL of today's runtime/api/domain/* (FLAT, minus carve-outs);
                    handlers/* (flat); thin facade packages backlog/claims/
                    lifecycle/projects/qa/deployment re-export from the flat modules
    sessions/       the authority half of today's runtime/harness session logic
    board/          DB-backed render half (minus the pure art carve-outs)
    cli/            db_router*, raw_query*, board_rebuild_timing_events (dev-fenced)
    db/migrations/  the migrations/ drop-zone
    engines/        ALL of today's runtime/api/engines/* (flat)
    tools/          core/dev tooling (minus image_to_emoji_art*)
    docker/         entrypoint, healthcheck (NET-NEW, for the local-core launcher)
```

Dependency DAG (arrows = "may import"): `contracts → stdlib/pydantic`;
`cli → contracts + transport`; `harness → contracts + transport (+ cli substrate)`;
`core → contracts + cli + harness` (the server reuses the client substrate and the
client-neutral harness-identity helpers; the reverse edges stay forbidden). Every
other edge is forbidden and import-graph-tested.

## Dev bootstrap (REQUIRED before running the test suite)

The four packages are not auto-importable from a bare checkout — homebrew Python is
PEP-668 externally-managed, so editable install is the dev/test mechanism. Run ONCE
per checkout/worktree (and again after a new package appears):

```bash
pip3 install -e packages/yoke-contracts -e packages/yoke-cli \
    -e packages/yoke-harness -e packages/yoke-core \
    --no-deps --break-system-packages
```

This puts `yoke_contracts`/`yoke_cli`/`yoke_harness`/`yoke_core` on
site-packages so BOTH in-process pytest AND the subprocess `python3 -m ...`
invocations (the `service_client` / `db_router` / dispatch CLI tests spawn fresh
interpreters) resolve them — exactly as the end-state product wheel will. `--no-deps`
because the third-party deps are already present; `--break-system-packages` because
these are the project's own new packages (only-additive names, zero conflict).

**The trap:** without this install, in-process collection looks clean but ~338+
subprocess tests fail with `ModuleNotFoundError: yoke_contracts`. A pytest
`pythonpath` covers only in-process and hides this asymmetry, so it was removed — the
honest green boundary requires the install. The editable install points at THIS
worktree's `src` dirs; redo it after switching worktrees. The end-state wheel/pipx
install (and the AC-31 clean-install smoke) supersede it.

## Decision 1 (harness split) — RESOLVED

The client/authority boundary for the harness is **already drawn in code** by the
Phase-3 hook-relay work; Decision 1 is physical separation + ~11 function-level
splits, not a greenfield partition. Verified against the live tree (Agent C):

- **~24 client-adapter modules → `yoke_harness`** (launch/parse/render/relay; no DB).
- **~13 authority modules → `yoke_core`** (DB/events/session/claim mutation, packet render).
- **~8 type modules → `yoke_contracts`** (incl. `harness_hook_ordering`, today in
  `runtime/api/domain/`, which is stdlib-pure and belongs with `chain_registry`).
- **11 SPLIT files** broken at the function level (the real hand-work) — full
  boundaries in `carve-out-harness.md`.

Verified corrections to the prior first-pass: `codex_db_resolution` → harness (it
resolves a DB *path string*, no connection); `service_client` is a **3-way** split
(path/env helpers + subprocess-CLI drivers → harness; only
`refresh_session_model_if_placeholder` is true direct-DB → core); `session_dispatch`
cleanup needs **no new core module** (`run_session_end_cleanup` already lives in
`session_end_cleanup`).

## Decision 2 (local guardrail home) — RESOLVED

Home: **`yoke_harness/guardrails/`**. The Bash PreToolUse chain registers **16
lints, not 7** (authoritative source: `harness_hook_ordering.HOOK_ORDERING`).

- **11 PURE-LOCAL** (move as-is, zero reads, offline): `lint_destructive_git`,
  `lint_python_runtime_import_in_tmp`, `lint_workspace_cwd_match`,
  `lint_subagent_background`, `lint_db_cmd`, `lint_tc_label`,
  `lint_pipe_to_truncator`, `lint_structured_field_transform_shell`,
  `lint_shell_quoted_function_payload`, `lint_no_agent_runtime_api_import_from_c`,
  `lint_no_agent_curl_against_yoke_api`.
- **2 NEEDS-CACHED-READ** (direct `db_helpers.connect()` today → convert to cached
  HTTPS read, fail-open): `lint_session_cwd`, `lint_long_command_polling`.
- **1 PRECEDENT** (already dispatcher-mediated via `call_dispatcher`, fail-open):
  `lint_main_commit` — the template the other two adopt.

The lint *logic* (pure path-string matching) is client-safe and moves to
`guardrails/`; the **DB reads it depends on stay in core** and are exposed as
cached read functions over the API (`claimed_worktrees`, `recent_bash_commands`,
`active_worktree_items`+`strategy_docs` — see `net-new.md`). The codemod MUST NOT
drag `session_claimed_worktrees` into the harness package.

## Slice execution order + green-boundary strategy

Phase 1 is **sequential, single worktree** (this one). Parallel-write fan-out is
forbidden — this is the highest-collision surface in the tree. The bulk is a
scripted codemod keyed to `codemod-rules.md`; the hand-work is the ~11 harness
splits, the contracts consolidations/splits, and the net-new authoring. The tree
returns to **green at each slice boundary**; transient-red *within* a slice is
acceptable; the hard-delete of `runtime.api`/`runtime.harness` is the FINAL slice.

1. **Slice 0** — this published move-map + File Budget/path-claim widen. (gate)
2. **Slice 1** — four package skeletons + root tooling + the machine-readable
   frozen codemod rule module + the codemod script (dry-run validated). Additive,
   green.
3. **Slice 2** — `yoke_contracts` extraction (foundation; everything imports it):
   move the ~20 contracts carve-outs with their consolidations/splits + author the
   net-new schema models + rewrite every importer of those specific modules. Green.
4. **Slice 3** — `yoke_core` consolidation: the bulk codemod (~1,400 modules +
   ~2,700 referencing files), including the authority half of the harness and the
   dev-fenced `cli/` exceptions. Green.
5. **Slice 4** — guardrail evaluation slice: `yoke_harness/guardrails/` + the 2
   cached-read conversions + the 3 core read endpoints. Green.
6. **Slice 5** — `yoke_cli` extraction: commands/transport/config/auth/project-
   install applier/browser-runtime home + the transport chokepoint split + the
   net-new local-core launcher + `yoke db read`. Green.
7. **Slice 6** — `yoke_harness` client-adapter extraction + the 11 function-level
   splits. Green.
8. **Slice 7** — hard-delete the old `runtime.api`/`runtime.harness` namespaces;
   fail tests on any residual production import. Green.
9. **Slice 8** — import-graph enforcement tests + clean-install smoke (psycopg
   absence, local-core container flow). Green.
10. **Slice 9** — docs + plan alignment.

Note on practicality: 2 and 3 are large. The codemod does the textual bulk; the
authored hand-work is bounded by the carve-out + net-new lists. Each slice ends
with `python3 -m pytest runtime/api/ runtime/harness/` (or the moved equivalent)
green before commit.

## Corrections to the spec first-pass (folded into this map)

1. `service_client_structured_api_adapter.py` (the transport chokepoint, eagerly
   imports `yoke_function_dispatch.dispatch` at L42) is **missing from the File
   Budget** — added.
2. `harness_hook_ordering.py` (today `runtime/api/domain/`, stdlib-pure) moves to
   `yoke_contracts.hook_runner.hook_ordering` — added.
3. Two mandatory transitive deps the spec omitted: `runtime.api.board.config_paths`
   (pure; `art_config` breaks without it) and `runtime.api.domain.field_note_text`
   (pure NamedTuple; `yoke_function_models` needs `FOOTER`; also core-consumed →
   genuine shared surface).
4. `project_contract_art_data.py` is **2777 lines** (not ~2400); only 2 symbols —
   `_ART_GLYPHS` (~39 lines, keep inline) + `MIXED_EMOJI_COLUMNS` (~2729 lines →
   package-data `.txt`).
5. PreToolUse lints are **16, not 7**.
6. `codex_db_resolution` is client (harness), not core.
7. The prod-flag predicate AC-16 requires is **net-new** — no `is_prod` field
   exists on the connection contract today. Designable from the spec (env
   classification, not DSN sniffing); see `net-new.md`.

## Risks / open items

- **Highest codemod risk:** the `domain.*` catch-all (888 modules) must be the LAST
  domain rule; the 3-way splits (`machine_config*`, `project_*`, `session*`) MUST be
  exact-match exceptions ordered first. A glob mis-routes core modules into client
  packages and silently breaks the no-psycopg / forbidden-edge guarantees.
- **Coordination split (Decision 2):** `session_claimed_worktrees` (DB read) stays
  core and becomes an API read; only the lint path-matching logic goes to harness.
- **Net-new prod-flag attribute:** which binding attribute marks an env prod is a
  contract addition; implemented as an explicit `prod` flag on the connected-env
  binding (default false; true for `prod`/`cloud-prod`). No operator input needed —
  the spec mandates env classification.
- **Architecture_impact:** stays `path_context_only` (touches inherited path-context
  families, not the model payload) unless Slice 5/6 edits the architecture model.
