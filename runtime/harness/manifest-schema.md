# Harness Manifest Schema

*Yoke-owned schema for harness capability manifests. Claude, Codex, and Cursor carry Yoke-shaped manifests in this single shared schema. This file is the canonical contract.*

The harness manifest IS the substrate capability contract Yoke refers to as `harness_contract` in operator orientation and packet docs. It declares hooks, env / session identity, cwd binding, adapter render format, supported commands, disabled paths, and known parity limits. `harness_contract` is deliberately distinct from the LLM-facing `schema_api_context` packet roles (`main_agent`, `architect_agent`, `engineer_agent`, `tester_agent`, `simulator_agent`, `boss_agent`) — the two layers never overlap, and the renderer does not produce a packet body for `harness_contract`. Adding a new harness adapter means writing or updating its manifest under this schema, not adding a new `schema_api_context` role.

The harness manifest is a JSON document at `runtime/harness/{harness_id}/manifest.json` that declares one harness's identity, runtime requirements, bootstrap mechanisms, supported affordances, telemetry posture, fallback behavior, and canonical-agents posture. Yoke core reads it to derive supported paths, check version floors at runtime, and surface drift through doctor checks.

Today, three manifests exist in this schema:

- `runtime/harness/claude/manifest.json`
- `runtime/harness/codex/manifest.json`
- `runtime/harness/cursor/manifest.json`

The schema below is the only canonical source. Renderers, drift checks, and runtime consumers read against these field names; manifest authors write against them.

## Top-level fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `_generated` | string | Yes | Generated-file marker written by the substrate renderer. Names the renderer (`yoke_core.domain.agents_render`) and the Python source dict the file was rendered from (`yoke_core.domain.agents_render_manifests.CLAUDE_MANIFEST` / `CODEX_MANIFEST` / `CURSOR_MANIFEST`). Its presence flags the file as machine-generated — do not hand-edit. |
| `harness_id` | string | Yes | Stable harness family identifier (e.g., `claude-code`, `codex`). Must match the directory name under `runtime/harness/`. |
| `cli` | object | Yes | Native command identity and discovery facts shared by PATH repair, relay probes, and launch resolution. See [Native CLI](#native-cli). |
| `runtime_minimums` | object | Yes | Minimum runtime versions for each operating mode. See [Runtime minimums](#runtime-minimums). |
| `bootstrap` | object | Yes | Bootstrap mechanism configuration. See [Bootstrap](#bootstrap). |
| `identity` | object | Yes | Session-identity sources for `executor`, `provider`, `model`, `workspace`. See [Identity](#identity). |
| `supports` | object | Yes | Affordance and command-source posture. See [Supports](#supports). |
| `session_control` | object | Yes | Versioned per-surface facts used to compute session messaging and launch routes. See [Session control](#session-control). |
| `agent_wake` | object | Yes | Whether the harness can resume an idle model turn, by which primitive, and on what evidence. See [Agent wake](#agent-wake). |
| `worktree_hook_enablement` | object | Yes | Operations that make the harness hook chain live and workspace-bound in linked worktree lanes. See [Worktree hook enablement](#worktree-hook-enablement). |
| `telemetry` | object | Yes | Telemetry source posture. See [Telemetry](#telemetry). |
| `fallback` | object | Yes | Behavior when affordances or paths are unsupported. See [Fallback](#fallback). |
| `canonical_agents` | object | Yes | Canonical-agent body sourcing posture. See [Canonical agents](#canonical-agents). |

All top-level fields are required for every harness manifest. Optional structure lives inside individual fields.

## Native CLI

The canonical source is `yoke_contracts.harness_cli_manifest`; renderers and
runtime consumers use that one registry rather than spelling harness commands
again.

| Key | Type | Description |
|-----|------|-------------|
| `surface_id` | string | Session surface served by this native command (for example, `codex-cli`). |
| `executable` | string | Command name the vendor installs (for example, `cursor-agent`). |
| `version_args` | list[string] | Arguments used by the bounded version probe. |
| `bundled_candidates` | list[string] | Optional absolute executable paths inside a vendor application bundle. Empty when no supported bundled command exists. |

Installer PATH repair reads this manifest registry, resolves each installed
command from the ambient installer PATH or a declared bundle candidate, and
adds the resolved parent directory to both login and non-login/SSH startup
surfaces. Missing commands remain a reported, re-runnable state; the standard
Yoke tool directory is still added for later installs.

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

## Session control

The object is rendered from
`yoke_contracts.session_control.SESSION_SURFACE_CAPABILITIES`; manifests do
not author a second capability matrix.

| Key | Type | Description |
|-----|------|-------------|
| `source` | string | Canonical Python contract that owns the facts. |
| `surfaces` | object | Closed mapping for only this harness family's known surfaces. |
| `inline_context_source` | string | Canonical Python contract for the inline hook-context ceiling. |
| `inline_context_bytes` | integer | That ceiling in bytes; runtime composition reads the Python contract, not this JSON. |

Each surface value carries `minimum_version`, `inject_events`, `create`,
`message_active`, `message_idle`, `message_stopped`,
`stop_denial_continuation`, `relay_stop_denial_continuation`,
`liveness_process_names`, and `wake_authority`. Route and Stop continuation
fields use the closed interface vocabulary
`supported | private | none`. `wake_authority` uses the closed vocabulary
`native | operator` and names who may resume a session on this surface.
`native` lets Yoke drive the harness's own resume; `operator` means native
resume is unsupported and only the person sitting in front of the window may
wake it, because resuming an open desktop conversation headlessly forks the
transcript they are reading. Every desktop surface declares `operator`, and
the wake path reads this field rather than inferring the stance from a route:
no version and no same-machine peer binary opens a wake route for such a
surface, `yoke session-control session wake` refuses it with that guidance,
and its pending message is delivered by hook injection the moment its
operator types. A create-capable surface may also declare
`native_create_timeout_seconds`, the soft bound after which a still-live
native is reported as slow and continues under the launch deadline rather
than being killed or classified as failed. `stop_denial_continuation` says
whether a denied
Stop is proven to resume the same model turn; a policy that needs continuation
must allow and durably defer work when this field is `none`.
`relay_stop_denial_continuation` applies the same proof specifically to a
session correlated with a Yoke relay launch. The Stop gate requires both facts
to be `supported` for a relay worker, because an interactive CLI may honor a
block while its headless launch command cannot accept a later prompt.
`liveness_process_names` is a list of process basenames the surface permits as
liveness-only anchors. These anchors can prove a registered session's process
dead but never participate in ambient session identity, and shared-pid
contention remains unusable. Private routes fail closed unless the observed
executor version exactly satisfies their pinned adapter contract.
`inject_events` names the model-visible hook events that can lease and render a
pending message; it is independent of native wake/create support.

`inline_context_source` and `inline_context_bytes` are rendered from
`yoke_contracts.hook_inline_context`. Runtime composition reads that Python
contract, not this JSON. The integer is the harness's inline
`additionalContext` (or Cursor `additional_context`) ceiling: composed hook
context is capped there so a vendor persist-to-file preview cannot hide a
Fleet delivery behind a hint. Codex's value is the vendor
`additionalContextLimit` default; Claude Code and Cursor use the shared
envelope ceiling.

## Agent wake

The object is rendered from
`yoke_contracts.harness_wake_capability.HARNESS_WAKE_CAPABILITIES`. It is the
single authority for what a harness can do with an out-of-band wake; no
document, skill, agent body, or rules file states one of these facts on its
own. Teaching surfaces that show the capability to a reader render it through
`yoke_core.tools.render_harness_capability_inline`, and a surface that only
explains a consequence names the field it depends on.

An **idle wake** resumes a model turn *after* that turn has ended — the
property that decides whether a session can arm a background watcher and be
woken per match, or must keep the turn alive and poll. A **timer wake** is the
same resumption the session schedules for itself.

| Key | Type | Description |
|-----|------|-------------|
| `source` | string | Canonical Python contract that owns the facts. |
| `idle_wake` | string | `supported` \| `none` \| `unverified`. |
| `idle_wake_mechanism` | string | Named primitive that performs the idle wake (for example, `Monitor`, `notify_on_output`). Empty when the class is not `supported`. |
| `timer_wake` | string | `supported` \| `none` \| `unverified`. |
| `timer_wake_mechanism` | string | Named primitive that performs the timer wake. Empty when the class is not `supported`. |
| `verified_on_surface` | string | Session surface the probe ran against. Empty when unverified. |
| `evidence` | string | How the answer was established — what was measured, and what the measurement showed. |

`unverified` is a first-class value and the default for an unknown harness id:
a harness nobody has probed says so rather than inheriting a neighbour's
answer. Adding a harness adapter means adding its measured entry to the
contract before any surface states what it can do.

## Worktree hook enablement

This object is the harness adapter's contribution to linked-lane preparation.
The worktree creator reads the manifest and executes the declared operations;
it does not contain a harness-specific branch for each adapter.

| Key | Type | Description |
|-----|------|-------------|
| `config_path` | string | Repo-relative native hook configuration path that the worktree must expose. |
| `operations` | list[string] | Ordered enablement operations. Supported values are `verify_hook_config`, `mirror_hook_trust`, `seed_directory_approval`, and `verify_environment_export`. |
| `environment` | object | Workspace export used by hook subprocesses. |

The `environment` object has two required string keys:

| Key | Description |
|-----|-------------|
| `root_variable` | Environment variable containing the lane's workspace root (`YOKE_ROOT`). |
| `root_expression` | Shell expression used to resolve that root from the harness payload or current directory. |

An operation may be omitted when the harness does not need that local
affordance. For example, Codex mirrors user-granted path trust while Claude
seeds its existing per-directory approval; both still verify the native hook
configuration and workspace export.

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

All three manifest files are generated artifacts: the substrate renderer (`yoke_core.domain.agents_render`) materializes them from the Python source dicts in `yoke_core.domain.agents_render_manifests` (`CLAUDE_MANIFEST` / `CODEX_MANIFEST` / `CURSOR_MANIFEST`) and stamps each with the `_generated` marker. The `session_control` and `agent_wake` objects are composed from `yoke_contracts.session_control` and `yoke_contracts.harness_wake_capability` respectively, so those facts are authored in their contracts rather than in the manifest dicts. Author changes in the source dicts or the contract they read, then re-render via the `agents.render.run` function id (operator adapter: `yoke agents render`); `agents.render.check` surfaces drift between the source and the on-disk files. Hand-edits to the JSON files are overwritten on the next render.
