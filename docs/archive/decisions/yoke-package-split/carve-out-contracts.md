# Carve-out: yoke_contracts (YOK-1902)

All modules below scanned **DB/events/session/claim-free** (direct + first-order
transitive) against the live tree. Contracts may import only stdlib + pydantic +
pyfiglet + (optional) Pillow.

## Consolidation map (old → new file)

| New file | Consolidates (old modules) |
| :-- | :-- |
| `board_art/config.py` | `board.art_config` + `board.board_emoji` + `board.config_paths` |
| `board_art/render_seed.py` | `project_contract_art_shared` + `project_contract_art_ascii` |
| `board_art/variants.py` | `project_contract_art_mixed` (335 — trim header on move) |
| `board_art/variants_image.py` | `project_contract_art_image_mixed` (93) — kept separate (merge would be 428 > cap) |
| `board_art/image_to_emoji.py` | `project_contract_image_art` + `tools.image_to_emoji_art` |
| `board_art/image_geometry.py` | split-off validators from `project_contract_image_art` (it is 349 — 1 under cap) |
| `board_art/palette.py` | `project_contract_image_art_palette` |
| `board_art/image_decode.py` | `tools.image_to_emoji_art_decode` (sips/Pillow path) |
| `board_art/_data.py` + `board_art/data/mixed_emoji_columns.txt` | `project_contract_art_data` (split) |
| `board_art/__init__.py` (facade) | `project_contract_art` (re-export hub, preserve `__all__`) |
| `machine_config/schema.py` | `machine_config_contract` + `_projects` + `_example` |
| `api/function_call.py` | `yoke_function_models` |
| `scaffolds.py` | `project_contract_scaffolds` |
| `field_note_text.py` | `field_note_text` (shared — core also consumes) |

## Oversized-file split plans

**`project_contract_art_data.py` (2777 lines) → 2 pieces:**
- `board_art/_data.py` (~50 lines): keep `_ART_GLYPHS` dict inline (L8-46, tiny);
  add a loader that reads the emoji columns from package data.
- `board_art/data/mixed_emoji_columns.txt` (~2700 lines, pure Unicode, package
  data): the ~214 `MIXED_EMOJI_COLUMNS` blocks separated by a `\n---\n` sentinel.
  Loader: `importlib.resources.files("yoke_contracts.project_contract.board_art.data")
  .joinpath("mixed_emoji_columns.txt").read_text().split("\n---\n")` → rebuild tuple.
  Declare in `[tool.setuptools.package-data]` so wheels ship it. Both `_ART_GLYPHS`
  and `MIXED_EMOJI_COLUMNS` remain importable from `_data.py`.

**`project_contract_art_mixed.py` (335) + `project_contract_art_image_mixed.py`
(93):** do NOT merge (428 > 350). Keep two files — `variants.py` and
`variants_image.py`. If `variants.py` still grazes the cap after the move, peel
`_render_mixed_variants`/`_select_mixed_variants` into `variants_select.py`.

**`project_contract_image_art.py` (349):** split validators
(`_validate_dimension_constraints`, `_sniff_format`, `center_crop_box_for_aspect`)
into `board_art/image_geometry.py`; public `convert_image_to_emoji_block` +
`ImageEmojiBlock` stay in `image_to_emoji.py`.

## Net-new schema models (author the model; builder/renderer stays where it is)

These have a stable existing dict shape — mint a typed pydantic model mirroring it,
leave the builder/renderer in place.

**`api/cli_manifest.py` — `CliManifest`:** `manifest_version: int`, `subcommands:
list[CliSubcommandRow]`, `aliases: list[CliSubcommandRow]`; `CliSubcommandRow =
{tokens: list[str], function_id: str, usage: str}`. Constants `MANIFEST_VERSION`,
`MANIFEST_PATH`, `CACHE_TTL_S` move to the model module. The **builder
`build_manifest()` stays in `yoke_cli`** (it server-renders the grammar from the
registry); the fetch/cache/match helpers stay client.

**`api/install_bundle.py` — `InstallBundle`:** `bundle_schema: int`,
`yoke_version: str`, `project_id: int`, `project_slug: str`, `files:
list[BundleFile]`, `project_contract_files: list[BundleFile]`, `strategy_files:
list[BundleFile]`, `hooks: BundleHooks {claude_settings_hooks: dict, codex_hooks:
dict}`; `BundleFile = {path: str, content: str}`. `BUNDLE_SCHEMA` constant moves to
the model. **Builder `build_bundle()` + `server_tree_root()` + `_project_row` and
`InstallBundleError`/`ProjectNotFoundError` stay `yoke_core`** (DB read at
`install_bundle.py:160`).

**`api/install_manifest.py` — `InstallManifest`:** authoritative key set is
`project_install._MANIFEST_OWNED_KEYS` (`project_install.py:52-62`): `manifest_schema:
int`, `yoke_version: str`, `project_id: int`, `mode: str`, `files: dict[str,str]`
(path→hash), `contract_files: dict[str,str]`, `strategy_files: dict[str,str]`,
`created_settings_files: list[str]`, `hook_entries: dict[str, list[dict]]`. **Must
allow unknown-key passthrough** (`ConfigDict(extra="allow")`) — the code deliberately
carries forward keys written by newer CLIs (`project_install.py:190-197`). The
applier (`apply_bundle`/`install`/`refresh`) + all `project_install_*` siblings stay
`yoke_cli`.

## Mandatory transitive deps (spec omitted these)

- `runtime.api.board.config_paths` (pure path math; `art_config` breaks without it)
  → fold into `board_art/config.py`.
- `runtime.api.domain.field_note_text` (pure NamedTuple; `yoke_function_models`
  needs `FOOTER`) → `yoke_contracts.field_note_text`. It is **also core-consumed**,
  so it is a genuine shared surface (the codemod rewrites both the contracts and the
  core import sites).

## Contracts public surface (shallow `__init__` re-exports)

- **function-call** (from `api.function_call`): `FunctionCallRequest`,
  `FunctionCallResponse`, `ActorContext`, `TargetRef`, `FunctionWarning`,
  `FunctionError`, `HandlerOutcome`, `validate_function_id`.
- **board-art seed** (from `project_contract.board_art`): `render_board_art`,
  `BoardArtVariant`, `choose_art_word`, `generate_random_ascii_variant`,
  `generate_random_mixed_variant`, `generate_random_image_mixed_variant_detail`, +
  constants `MIXED_EMOJI_COLUMNS`, `ASCII_FIGLET_FONTS`, `ASCII_VARIANT_COUNT`,
  `MIXED_VARIANT_COUNT`, `FALLBACK_ART_WORD`.
- **board config/parsing** (from `board_art.config`): `ArtConfig`, `ArtVariant`,
  `parse_art_config`, `BLACK`, `WHITE`, `CELEBRATION_EMOJIS`, `STATUS_EMOJI` (board
  render consumers need these).
- **image-art** (from `board_art.image_to_emoji`/`.palette`):
  `convert_image_to_emoji_block`, `ImageEmojiBlock`, `EmojiColor`,
  `master_map_dimensions`, `target_emoji_dimensions`.
- **scaffolds** (from `project_contract.scaffolds`): `render_project_config`,
  `render_test_inventory`, `render_template_deviations`, `render_deploy_runbook`,
  `render_deploy_checklist`, `render_recovery_runbook`.
- **machine-config schema** (from `machine_config.schema`): `normalize_payload`,
  `validate_payload`, `selected_env`, `active_connection`, `local_postgres_envs`,
  `MachineConfigContractError`, `POSTGRES_TRANSPORTS`, `TRANSPORT_*`,
  `CREDENTIAL_KINDS`.
- **wire/file schemas** (new, from `api.*`): `CliManifest`, `CliSubcommandRow`,
  `InstallBundle`, `BundleFile`, `InstallManifest`.
- **hook-runner shared** (from `hook_runner.*`): `HookContext`, `HookDecision`,
  `RunControls`, `LOCAL_STATE_POLICIES`, `ordered_pipeline_for` (hook ordering).

`_ART_GLYPHS` and the `_data` loader stay non-exported internals (leading
underscore); only `MIXED_EMOJI_COLUMNS` is re-exported (existing core consumer).

## Board-render consumers to rewrite (core, import contracts)

`art_config`/`board_emoji` are also imported by `board.{art_render,art_progress,art,
art_stats,art_rainbow,art_select}` (all → `yoke_core.board.*`). Core-imports-
contracts is allowed; the codemod rewrites those ~6 import sites to
`yoke_contracts.project_contract.board_art.config`.
