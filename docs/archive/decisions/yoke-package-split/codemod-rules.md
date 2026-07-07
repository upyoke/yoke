# Codemod Rules — frozen prefix rewrites (YOK-1902)

The bulk move is a **scripted codemod** keyed to these rules. They are an **ordered
rule list** (most-specific / longest-prefix first), NOT an unordered dict. The
machine-readable form lives in `packages/_codemod/rules.py` (Slice 1); this file is
the human-reviewable source of truth.

## How the codemod applies rules

For every `.py` / doc / config file in the rewrite surface:
1. Resolve each module's **physical destination** (where the file `git mv`s to).
2. Rewrite every dotted reference (`import X`, `from X import`, and string mentions
   of the dotted path) using the ordered rules: the **first matching rule wins**.
3. Exact-module rules (Tier A carve-outs, Tier C dev-fences) are checked BEFORE the
   Tier B subtree-prefix defaults. Within Tier B, `domain.handlers.*` and
   `domain.migrations.*` are checked before the `domain.*` catch-all.

The codemod uses an **explicit exact-name exception set** for everything that shares
a stem with a default rule. Globs are permitted ONLY on subtrees with zero internal
carve-outs: `engines.*`, `routes.*`, `domain.handlers.*`.

## Tier A — exact-module carve-out EXCLUSIONS (leave core; owned by contracts/cli/harness)

| Old module (exact, dotted) | New module | Pkg |
| :-- | :-- | :-- |
| `runtime.api.domain.yoke_function_models` | `yoke_contracts.api.function_call` | contracts |
| `runtime.api.domain.machine_config_contract` | `yoke_contracts.machine_config.schema` | contracts |
| `runtime.api.domain.machine_config_contract_projects` | `yoke_contracts.machine_config.schema` (consolidate) | contracts |
| `runtime.api.domain.machine_config_contract_example` | `yoke_contracts.machine_config.schema` (consolidate) | contracts |
| `runtime.api.domain.field_note_text` | `yoke_contracts.field_note_text` | contracts |
| `runtime.api.domain.project_contract_scaffolds` | `yoke_contracts.project_contract.scaffolds` | contracts |
| `runtime.api.domain.project_contract_art` | `yoke_contracts.project_contract.board_art` (facade `__init__`) | contracts |
| `runtime.api.domain.project_contract_art_shared` | `yoke_contracts.project_contract.board_art.render_seed` | contracts |
| `runtime.api.domain.project_contract_art_ascii` | `yoke_contracts.project_contract.board_art.render_seed` (consolidate) | contracts |
| `runtime.api.domain.project_contract_art_mixed` | `yoke_contracts.project_contract.board_art.variants` | contracts |
| `runtime.api.domain.project_contract_art_image_mixed` | `yoke_contracts.project_contract.board_art.variants_image` | contracts |
| `runtime.api.domain.project_contract_art_data` | `yoke_contracts.project_contract.board_art._data` (+ package-data) | contracts |
| `runtime.api.domain.project_contract_image_art` | `yoke_contracts.project_contract.board_art.image_to_emoji` | contracts |
| `runtime.api.domain.project_contract_image_art_palette` | `yoke_contracts.project_contract.board_art.palette` | contracts |
| `runtime.api.tools.image_to_emoji_art` | `yoke_contracts.project_contract.board_art.image_to_emoji` (consolidate) | contracts |
| `runtime.api.tools.image_to_emoji_art_decode` | `yoke_contracts.project_contract.board_art.image_decode` | contracts |
| `runtime.api.board.art_config` | `yoke_contracts.project_contract.board_art.config` | contracts |
| `runtime.api.board.board_emoji` | `yoke_contracts.project_contract.board_art.config` (consolidate) | contracts |
| `runtime.api.board.config_paths` | `yoke_contracts.project_contract.board_art.config` (consolidate) | contracts |
| `runtime.api.domain.harness_hook_ordering` | `yoke_contracts.hook_runner.hook_ordering` | contracts |
| `runtime.api.domain.machine_config` | `yoke_cli.config.machine_config` | cli |
| `runtime.api.domain.machine_config_writer` | `yoke_cli.config.machine_config_writer` | cli |
| `runtime.api.domain.machine_config_status` | `yoke_cli.config.machine_config_status` | cli |
| `runtime.api.domain.project_install` | `yoke_cli.commands.project_install` | cli |
| `runtime.api.domain.project_install_*` (files/git_hooks/hooks/source_link/uninstall/validate) | `yoke_cli.commands.project_install_*` | cli |
| `runtime.api.domain.project_install_transport` | `yoke_cli.commands.project_install_transport` (in-process leg core-lazy) | cli |
| `runtime.api.domain.project_install_strategy` | `yoke_cli.commands.project_install_strategy` (in-process leg core-lazy) | cli |
| `runtime.api.domain.browser_runtime_home` | `yoke_cli.browser_runtime.home` | cli |
| `runtime.api.domain.session_ambient_identity` | `yoke_cli.config.session_ambient_identity` | cli |
| `runtime.api.domain.session_process_anchors` | `yoke_cli.config.session_process_anchors` | cli |
| `runtime.api.service_client_shared_session_resolver` | `yoke_cli.config.session_resolver` | cli |
| `runtime.api.cli.*` (all CLI UX, minus Tier C) | `yoke_cli.*` (see carve-out-cli.md for exact map) | cli |
| `runtime.harness.*` (client adapters + `lint_*` guardrails) | `yoke_harness.*` (see carve-out-harness.md) | harness |

The contracts/cli/harness per-module placements above are authoritative summaries;
the full carve-out tables (with consolidations and split boundaries) are in the
`carve-out-*.md` siblings.

## Tier C — STAYS CORE but dev/test-fenced (AC-14/AC-16) — ordered BEFORE cli/service_client rules

| Old module (exact) | New module |
| :-- | :-- |
| `runtime.api.cli.db_router` (+ `db_router_dispatch`/`_init`/`_help`/`_suggestions`) | `yoke_core.cli.db_router*` |
| `runtime.api.cli.raw_query` (+ `raw_query_catalog`/`raw_query_test_helpers`) | `yoke_core.cli.raw_query*` |
| `runtime.api.cli.board_rebuild_timing_events` | `yoke_core.cli.board_rebuild_timing_events` |
| `runtime.api.service_client_structured_api_adapter` (in-process `dispatch` leg only) | `yoke_core` (client transport split out — see carve-out-cli.md) |
| `runtime.api.service_client*` (whole family, ~70 modules) | `yoke_core.api.service_client*` |
| `runtime.api.domain.yoke_function_dispatch` (+ `_*`) | `yoke_core.domain.yoke_function_dispatch*` |
| `runtime.api.domain.db_backend` / `db_helpers` | `yoke_core.domain.*` |
| `runtime.api.domain.session_claimed_worktrees` | `yoke_core.domain.session_claimed_worktrees` (exposed as cached read) |

## Tier B — DEFAULT core rules (apply after Tier A/C miss)

| Old prefix | New prefix | Notes |
| :-- | :-- | :-- |
| `runtime.api.app_factory` | `yoke_core.api.app_factory` | |
| `runtime.api.server_entrypoint` | `yoke_core.api.server_entrypoint` | |
| `runtime.api.main` / `main_db` / `main_models` / `main_route_adapters` | `yoke_core.api.*` | |
| `runtime.api.http_auth` | `yoke_core.api.http_auth` | |
| `runtime.api.observability*` / `routing_config` / `container_healthcheck` / `repo_root` | `yoke_core.api.*` | |
| `runtime.api.routes.X` | `yoke_core.api.routes.X` | glob OK (no carve-outs) |
| `runtime.api.domain.handlers.X` | `yoke_core.domain.handlers.X` | **order before `domain.*`**; glob OK |
| `runtime.api.domain.migrations.X` | `yoke_core.db.migrations.X` | **order before `domain.*`** |
| `runtime.api.domain.X` | `yoke_core.domain.X` | **catch-all — LAST domain rule** |
| `runtime.api.engines.X` | `yoke_core.engines.X` | glob OK (zero carve-outs) |
| `runtime.api.tools.X` | `yoke_core.tools.X` | minus `image_to_emoji_art*` (Tier A) |
| `runtime.api.board.X` (non-carveout) | `yoke_core.board.X` | minus art_config/board_emoji/config_paths (Tier A) |

## Collision exceptions the codemod MUST encode (carve-out shares a prefix with a default)

These are why the codemod uses an exact-name exception set, never prefix globs, on
these stems:

1. **`machine_config*` is 3-way.** `machine_config_contract*` → contracts;
   `machine_config`/`_writer`/`_status` → cli. No `machine_config*` glob.
2. **`project_*` is 3-way.** `project_contract_art*`/`project_contract_image_art*`/
   `project_contract_scaffolds` → contracts; `project_install*` → cli; but
   `projects`, `projects_breakage_policy`, `projects_seed_*`, `project_capabilities`,
   `project_structure*`, `project_renderer`, `project_scratch_dir` → **core**. No
   `project*` glob — it would be catastrophic.
3. **`session*` carve-out is exactly two.** `session_ambient_identity` +
   `session_process_anchors` → cli; everything else (`session_claimed_worktrees`,
   `sessions_*`, `session_contract`, `session`) → core.
4. **`cli.*` vs Tier-C dev-fenced.** `db_router*`/`raw_query*`/
   `board_rebuild_timing_events` stay core — ordered before the `cli.* → cli`
   catch-all.
5. **`service_client_shared_session_resolver` → cli** vs the rest of
   `service_client*` → core. One module leaves; exact-match, ordered first.
6. **board art modules → contracts** vs `board.* → core`. Exact-match list before
   the board catch-all.
7. **`domain.handlers.*` / `domain.migrations.*` ordered before `domain.*`** so they
   retarget correctly rather than collapsing into flat `yoke_core.domain.*`.

## Rewrite surface (files the codemod edits)

- All `.py` under `runtime/` (source moves + internal import rewrites) and `tests/`.
- Doc/config references: `docs/**`, `.agents/skills/**`, `.yoke/strategy/**`,
  `pyproject.toml`, `runtime/api/conftest.py` and other conftests, any `*.md`/`*.json`
  mentioning the dotted paths.
- Tests move with the module they cover (`test_<module>.py` follows `<module>`).

## Load-bearing strings (verified file:line anchors for the hand-edits)

- `runtime/api/service_client_structured_api_adapter.py:42` — `from
  runtime.api.domain.yoke_function_dispatch import dispatch` (the forbidden edge;
  split into client `yoke_cli.transport.dispatcher` + lazy/core dispatch leg).
- `runtime/api/cli/raw_query.py:102` — `db_backend.connect_psycopg()` (dev-fenced).
- `runtime/api/cli/board_rebuild_timing_events.py:12` — `from ...domain.events import
  emit_event` (→ core).
- `runtime/api/domain/lint_session_cwd.py:96` — `return db_helpers.connect()`
  (convert to cached read).
- `runtime/api/domain/lint_long_command_polling_evaluate.py:79` &
  `lint_long_command_polling_monitor_duplicate.py:97` — `db_helpers.connect(...)`
  (convert to cached read).
- `runtime/api/domain/lint_main_commit.py:124-130` — `call_dispatcher(function_id=
  "items.list.run", ...)` (the dispatcher-mediated precedent; no conversion).
- `runtime/harness/hook_runner/service_client.py:267` — `db_backend.connect(...)`
  (the one true core line in that module's 3-way split).
- `runtime/api/domain/harness_hook_ordering.py:134-151` — the authoritative 16-lint
  `HOOK_ORDERING` tuple.
- `runtime/api/app_factory.py:170-195` — router include block (add `db_read_router`).
- `runtime/api/domain/db_backend.py:188` `connect()` / `:209` `connect_psycopg()`,
  funnel `connected_env_readiness.py:190 connect_with_readiness()` — prod-refusal
  attach point.
- `runtime/api/domain/yoke_connected_env.py:89 load_active()` — env classification
  source for the prod-flag predicate.
- `runtime/api/domain/actor_permissions.py:21-33` (constants), `:50`
  (`PERMISSION_DESCRIPTIONS`); `yoke_function_permissions.py:41-75`
  (`permission_key_for`) — `db.read.raw` gate wiring.
