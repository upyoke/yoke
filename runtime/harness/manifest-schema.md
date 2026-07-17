# Harness Manifest Schema

*Yoke-owned schema for harness capability manifests. Both Claude and Codex carry Yoke-shaped manifests in this single shared schema. This file is the canonical contract.*

The harness manifest IS the substrate capability contract Yoke refers to as `harness_contract` in operator orientation and packet docs. It declares hooks, env / session identity, cwd binding, adapter render format, supported commands, disabled paths, and known parity limits. `harness_contract` is deliberately distinct from the LLM-facing `schema_api_context` packet roles (`main_agent`, `architect_agent`, `engineer_agent`, `tester_agent`, `simulator_agent`, `boss_agent`) — the two layers never overlap, and the renderer does not produce a packet body for `harness_contract`. Adding a new harness adapter means writing or updating its manifest under this schema, not adding a new `schema_api_context` role.

The harness manifest is a JSON document at `runtime/harness/{harness_id}/manifest.json` that declares one harness's identity, runtime requirements, bootstrap mechanisms, supported affordances, telemetry posture, fallback behavior, and canonical-agents posture. Yoke core reads it to derive supported paths, check version floors at runtime, and surface drift through doctor checks.

Today, two manifests exist in this schema:

- `runtime/harness/claude/manifest.json`
- `runtime/harness/codex/manifest.json`

The schema below is the only canonical source. Renderers, drift checks, and runtime consumers read against these field names; manifest authors write against them.

## Top-level fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `_generated` | string | Yes | Generated-file marker written by the substrate renderer. Names the renderer (`yoke_core.domain.agents_render`) and the Python source dict the file was rendered from (`yoke_core.domain.agents_render_manifests.CLAUDE_MANIFEST` / `CODEX_MANIFEST`). Its presence flags the file as machine-generated — do not hand-edit. |
| `harness_id` | string | Yes | Stable harness family identifier (e.g., `claude-code`, `codex`). Must match the directory name under `runtime/harness/`. |
| `runtime_minimums` | object | Yes | Minimum runtime versions for each operating mode. See [Runtime minimums](#runtime-minimums). |
| `bootstrap` | object | Yes | Bootstrap mechanism configuration. See [Bootstrap](#bootstrap). |
| `identity` | object | Yes | Session-identity sources for `executor`, `provider`, `model`, `workspace`. See [Identity](#identity). |
| `supports` | object | Yes | Affordance and command-source posture. See [Supports](#supports). |
| `telemetry` | object | Yes | Telemetry source posture. See [Telemetry](#telemetry). |
| `fallback` | object | Yes | Behavior when affordances or paths are unsupported. See [Fallback](#fallback). |
| `canonical_agents` | object | Yes | Canonical-agent body sourcing posture. See [Canonical agents](#canonical-agents). |

All top-level fields are required for every harness manifest. Optional structure lives inside individual fields.

## Runtime minimums

Object whose keys name operating modes and whose values are human-readable version strings (free-form). Today's modes:

| Key | Meaning |
|-----|---------|
| `wrapper_only` | Floor for the no-hook baseline path (correctness comes from Yoke core). |
| `hook_enhanced` | Floor for the optional hook-enhanced path (Pre/Post tool use, deny narratives, normalized tool events). |
| `tested_locally` | Latest version the operator has personally smoke-tested. Advisory; not a runtime gate. |

Doctor checks read `hook_enhanced` to enforce that the operator's installed harness build meets the declared floor. The floor must match the build that the matching deny smoke (e.g., Codex `apply_patch` deny smoke) has been verified against on the operator's machine.

## Bootstrap

| Key | Type | Description |
|-----|------|-------------|
| `spec_path` | string | Repo-relative path to the neutral bootstrap spec (`runtime/harness/bootstrap-spec.json`). |
| `mechanisms` | list[string] | Ordered list of bootstrap mechanisms the harness uses (e.g., `wrapper_command`, `optional_session_start_hook`, `harness_native_config`). |

The bootstrap spec is harness-neutral; the manifest names which delivery mechanisms the harness uses to load it.

## Identity

| Key | Type | Description |
|-----|------|-------------|
| `executor` | string | Stable harness executor identity used by Yoke core (e.g., `claude-code`, `codex`). |
| `provider_source` | string | Where the model provider value comes from (`runtime`, `harness_config`, `payload`). |
| `model_source` | string | Where the model identifier comes from (`runtime`, `harness_config`, `payload_thread_metadata`). |
| `workspace_source` | string | How the workspace path is resolved (`payload_cwd_then_git_root`, `git_root`). |

## Supports

| Key | Type | Description |
|-----|------|-------------|
| `command_source` | string | Where the command/path truth lives (`shared_yoke_registry`). The manifest never copies command lists. |
| `disabled_entrypoints` | list[string] | Top-level operator commands the harness explicitly cannot run (substrate limitation). Empty when no limitation applies. |
| `disabled_downstream_paths` | list[string] | Downstream paths the harness explicitly cannot run. Empty when no limitation applies. |
| `optional_local_affordances` | list[string] | Tool-neutral hook affordances the harness optionally exposes when the runtime floor is met. Canonical names: `session_start_hook`, `user_prompt_submit_hook`, `pre_tool_use_hook`, `post_tool_use_hook`, `stop_hook`. |

The affordance list is **tool-neutral**. Names like `bash_pre_tool_hook` or `bash_post_tool_hook` are obsolete — the universal hook ordering and policy pipeline matches across `Bash`, `Edit`, `Write`, and `apply_patch`, and the manifest must not encode a tool-specific shape.

## Telemetry

| Key | Type | Description |
|-----|------|-------------|
| `canonical_source` | string | Where the canonical telemetry stream comes from (`yoke_core`). |
| `optional_local_sources` | list[string] | Optional supplementary telemetry sources the harness can produce (`hook_logs`, `transcript_logs`). |

## Fallback

| Key | Type | Description |
|-----|------|-------------|
| `when_hooks_missing` | string | Behavior when the runtime floor for hooks is not met (`wrapper_only`). |
| `when_path_unsupported` | string | Behavior when a downstream path is not supported (`return unsupported to core`). |

## Canonical agents

| Key | Type | Description |
|-----|------|-------------|
| `source` | string | Reference into the bootstrap spec naming the canonical-agents tree (e.g., `runtime/harness/bootstrap-spec.json#canonical_agents`). |
| `consumption` | string | Positive descriptor of how the harness consumes canonical agents. Allowed values today: `generated` (Yoke's renderer materializes adapters under `runtime/harness/{harness_id}/agents/` and the harness reads them at runtime); `native` (the harness consumes the canonical bodies directly without an intermediate renderer); `discoverability` (the harness exposes the canonical-agents tree as discoverability metadata only — sessions do not lazy-load these bodies, but the path is surfaced for tooling). |

`consumption` must be a positive descriptor. The legacy `metadata-only` value is obsolete; use `discoverability` when the manifest only surfaces the path without runtime materialization.

## Versioning

The schema in this file is the contract. When new fields are added:

- Update this document first.
- Update the manifest source dicts (or note the new field is optional and document the default).
- Update doctor checks that read the affected field.

Both manifest files are generated artifacts: the substrate renderer (`yoke_core.domain.agents_render`) materializes them from the Python source dicts in `yoke_core.domain.agents_render_manifests` (`CLAUDE_MANIFEST` / `CODEX_MANIFEST`) and stamps each with the `_generated` marker. Author changes in the source dicts, then re-render via the `agents.render.run` function id (operator adapter: `yoke agents render`); `agents.render.check` surfaces drift between the source and the on-disk files. Hand-edits to the JSON files are overwritten on the next render.
