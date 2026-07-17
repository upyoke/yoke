# Harness Adapter Template

*Reusable template for integrating a new harness with Yoke. Every adapter must implement the five required parts described below. The [Harness Bootstrap Contract](harness-bootstrap.md) defines the neutral startup expectations that every adapter loads.*

*Last updated: 2026-04-05 (neutral bootstrap spec + prompt doctrine universalization)*

## Overview

A harness adapter is a thin layer between a specific agent runtime (Claude Code, Codex, a future harness) and Yoke's core operator interface. The adapter does not contain business logic -- it translates harness-native mechanisms (hooks, config files, CLI wrappers) into Yoke's neutral contract surface.

Every adapter must implement these five parts:

1. **Bootstrap Loader** -- loads the Yoke-owned startup contract
2. **Capability Manifest** -- declares identity and supported paths
3. **Session-Offer Builder** -- translates manifest into Yoke's offer format
4. **Route Wrapper** -- invokes only declared-supported Yoke commands
5. **Smoke-Test Matrix** -- validates both wrapper-only and hook-enhanced modes

A third harness should be able to instantiate this template without modifying Yoke core.

---

## Part 1: Bootstrap Loader

The bootstrap loader ensures the harness session starts with the same Yoke orientation context regardless of how the harness delivers it.

### Requirements

- Load the required files and commands listed in the [Harness Bootstrap Contract](harness-bootstrap.md) section 1 (Startup Reads).
- Work without hooks. A wrapper command or harness-native config mechanism is always sufficient.
- May optionally use a session-start hook when the harness runtime supports one.

### Mechanisms (choose one or more)

| Mechanism | Description | Hook dependency |
|-----------|-------------|-----------------|
| Wrapper command | An explicit entry script that reads required files and injects them into the session context before the first operator interaction. | None |
| Session-start hook | A harness-native hook event (e.g., `SessionStart`, `UserPromptSubmit`) that injects the same content automatically. | Yes -- requires the harness to support the hook event. |
| Harness-native config | The harness's own configuration includes the required files in the system prompt or context window at startup. | None |

### What to load

The canonical bootstrap content lives in `runtime/harness/bootstrap-spec.json`. The human rationale and delivery rules live in [harness-bootstrap.md](harness-bootstrap.md) section 1. Adapters should read the spec instead of duplicating the shared file/command list in harness-local docs or scripts.

### Degradation rule

If the preferred mechanism (e.g., a hook) is unavailable, the adapter must fall back to wrapper-command mode. Bootstrap must succeed in all cases. A harness that cannot load the required reads is not bootstrapped and must not proceed to operator interaction.

---

## Part 2: Capability Manifest

The capability manifest is a static or runtime-generated JSON document that declares what the harness is and what it can do. Yoke core reads this manifest to make routing and fallback decisions.

### Manifest JSON shape

```json
{
 "harness_id": "<string>",
 "runtime_minimums": {
 "wrapper_only": "<string>",
 "hook_enhanced": "<string | null>",
 "tested_locally": "<string | null>"
 },
 "bootstrap": {
 "spec_path": "<string>",
 "mechanisms": ["<string>"]
 },
 "identity": {
 "executor": "<string>",
 "provider_source": "<string>",
 "model_source": "<string>",
 "workspace_source": "<string>"
 },
 "supports": {
 "command_source": "shared_yoke_registry",
 "disabled_entrypoints": ["<string>"],
 "disabled_downstream_paths": ["<string>"],
 "optional_local_affordances": ["<string>"]
 },
 "telemetry": {
 "canonical_source": "<string>",
 "optional_local_sources": ["<string>"]
 }
}
```

### Field-level descriptions

#### Top-level fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `harness_id` | string | Yes | Unique identifier for this harness (e.g., `"claude-code"`, `"codex"`, `"api"`). |
| `runtime_minimums` | object | Yes | Version or environment requirements for each operating mode. |
| `bootstrap` | object | Yes | How this harness loads the Yoke startup contract. |
| `identity` | object | Yes | How this harness resolves session identity fields. |
| `supports` | object | Yes | What Yoke surfaces this harness can invoke. |
| `telemetry` | object | Yes | Where canonical telemetry comes from for this harness. |

#### `runtime_minimums`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `wrapper_only` | string | Yes | Minimum requirement for wrapper-only mode (e.g., `"any supported runtime"`). |
| `hook_enhanced` | string or null | No | Minimum requirement for hook-enhanced mode. Null means hooks are not available. |
| `tested_locally` | string or null | No | Specific version/build that has been locally verified. Informational. |

#### `bootstrap`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `spec_path` | string | Yes | Path to the neutral bootstrap spec JSON (for example `runtime/harness/bootstrap-spec.json`). The spec is the executable source of truth for startup reads. |
| `mechanisms` | array of strings | Yes | Bootstrap delivery mechanisms this adapter uses (e.g., `"wrapper_command"`, `"session_start_hook"`, `"harness_native_config"`). |

#### `identity`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `executor` | string | Yes | The harness identity value (e.g., `"claude-code"`, `"codex"`). Matches the `executor` session identity field in the bootstrap contract. |
| `provider_source` | string | Yes | How the adapter resolves the model provider (e.g., `"hardcoded"`, `"runtime"`, `"config"`). |
| `model_source` | string | Yes | How the adapter resolves the model identifier (e.g., `"hardcoded"`, `"runtime"`, `"config"`). |
| `workspace_source` | string | Yes | How the adapter resolves the workspace root (e.g., `"git_root"`). |

#### `supports`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `command_source` | string | Yes | For Yoke-owned harnesses, use `"shared_yoke_registry"`. Command/path truth is shared by default. |
| `disabled_entrypoints` | array of strings | No | Shared operator commands this harness cannot execute because of a concrete substrate limitation. Empty means inherit shared support. |
| `disabled_downstream_paths` | array of strings | No | Shared delivery paths this harness cannot execute because of a concrete substrate limitation. Empty means inherit shared support. |
| `optional_local_affordances` | array of strings | No | Tool-neutral hook events or local capabilities the harness supports (e.g., `"session_start_hook"`, `"pre_tool_use_hook"`, `"post_tool_use_hook"`). These are opt-in enhancements, not correctness requirements. |

#### `telemetry`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `canonical_source` | string | Yes | Where correctness-critical telemetry originates. Must be `"yoke_core"` -- harness-local hooks are never the canonical source. |
| `optional_local_sources` | array of strings | No | Additional local telemetry sources (e.g., `"hook_logs"`). These are informational, not authoritative. |

### Entrypoints vs downstream paths

The shared registry distinguishes two kinds of Yoke surfaces:

- **Entrypoints** are top-level `/yoke` operator commands (Tier 1 in the [bootstrap contract](harness-bootstrap.md) section 3). Yoke-owned harnesses inherit these commands from shared Yoke code unless their manifest declares a concrete limitation.

- **Downstream paths** are the delivery lanes that `/yoke do` routes into after the session offer. When `/yoke do` decides the next action, it checks the shared registry plus manifest-declared disabled paths to determine whether the harness can execute the chosen lane. If not, it falls back truthfully.

A harness with `command_source: "shared_yoke_registry"` inherits the shared operator and downstream surfaces. If a substrate cannot support one of those surfaces, declare the matching `disabled_entrypoints` or `disabled_downstream_paths` entry and document the limitation. Work requiring a disabled downstream path falls back rather than failing silently.

### Shared registry plus manifest limitations

For harnesses with a manifest, Yoke core derives the effective `downstream_paths` server-side from the shared registry and then applies limitations from the coarse harness manifest. Surface-specific executor values normalize back to the family manifest (`codex-desktop` -> `runtime/harness/codex/manifest.json`, `claude-vscode` -> `runtime/harness/claude-code/manifest.json`). A harness's session-offer-time `supported_paths` argument is ignored for Yoke-owned harnesses. The shared registry is the command/path source; the manifest is the limitation and affordance declaration; the session offer is the transport.

**Shared Yoke code is the command/path source of truth for Yoke-owned harnesses.** A harness that does not ship a manifest falls into the backward-compat branch — an empty effective list is treated as "all downstream paths supported". Adapters that want truthful fallback enforcement should either add a manifest under `runtime/harness/{executor}/manifest.json` (or explicitly normalize surface-specific executors back to a coarse family manifest) or, for non-Yoke-owned adapters, continue to pass `supported_paths` explicitly at session-offer time.

---

## Part 3: Session-Offer Builder

The session-offer builder translates the adapter's runtime identity and declared limitations into the format that `/yoke do` expects. For Yoke-owned harnesses, truthful downstream-path support is normally derived server-side from the shared registry plus manifest limitations rather than passed as an operator-facing argument.

### Requirements

- Read identity fields from the capability manifest's `identity` section.
- Resolve runtime values (provider, model) from the source specified in the manifest.
- Ensure Yoke core can resolve truthful downstream-path support from the shared registry plus manifest limitations. Only non-Yoke-owned adapters without a Yoke-managed manifest should pass `supported_paths` explicitly to the shared session-offer API.
- Include the `supports.optional_local_affordances` for informational enrichment.

### Session-offer parameters

The session offer currently accepts these parameters (from `yoke_core.api.service_client` or the `/v1/session/offer` API endpoint):

| Parameter | Source | Required |
|-----------|--------|----------|
| `--executor` | `identity.executor` | Yes |
| `--provider` | Resolved from `identity.provider_source` | Yes |
| `--model` | Resolved from `identity.model_source` | Yes |
| `--workspace` | Resolved from `identity.workspace_source` | Yes |
| `--session-id` | Harness-generated canonical id (required for supported harnesses; see `session-identity-contract.md`). Auto-generated fallbacks are rejected for `claude-code` / `codex` at the service boundary. | Yes |
| `--supported-paths` | Ignored for supported harnesses; Yoke core derives the effective list from the shared registry plus coarse-manifest limitations (`codex-desktop` -> `runtime/harness/codex/manifest.json`). Still accepted for unsupported/external adapters without a manifest. | No |
| `--lane` | Yoke core executor-default-lane config, unless explicitly overridden by a low-level adapter | No |

### Backward compatibility

When no manifest exists for the executor (e.g., `claude-code` today), Yoke treats the harness as supporting all downstream paths. This preserves existing Claude Code sessions without requiring a manifest. Adding a manifest later is opt-in and only changes the effective `supported_paths` set when the manifest declares explicit limitations.

---

## Part 4: Route Wrapper

The route wrapper provides bootstrap and identity guidance for shared Yoke commands, then lets Yoke core own command execution semantics.

### Requirements

- Accept a routing decision from `/yoke do` (or from the operator directly).
- Check the requested command against shared registry support plus manifest-declared disabled entrypoints/downstream paths.
- If the command is supported, hand off to the corresponding `/yoke` command through the harness-native skill or prompt surface.
- If the command is not supported, return a clear unsupported-path response. Do not attempt the command. Do not silently skip it.

### Wrapper-only vs hook-enhanced

| Mode | Description | When to use |
|------|-------------|-------------|
| Wrapper-only | The launcher provides bootstrap, identity, and handoff guidance. No hooks fire. All correctness comes from Yoke core and repo-local skills. | Default. Always works. |
| Hook-enhanced | The same shared handoff runs and harness hooks fire for additional guardrails/telemetry. | Opt-in when the harness runtime supports the relevant hooks. |

Both modes must produce identical correctness outcomes. Hook-enhanced mode adds guardrails and telemetry but must not be required for correct operation. If a hook is unavailable, the wrapper-only path remains safe.

### What the wrapper must NOT do

- Invoke Tier 3 raw Python entrypoints directly (for example, lower-level item create clients).
- Invoke Tier 2 internal sub-skills directly unless routed by Yoke core.
- Bypass operator-command safety gates.
- Claim support for a disabled downstream path without removing or narrowing the manifest limitation.

---

## Part 5: Smoke-Test Matrix

Every adapter must include a smoke-test matrix that validates both operating modes.

### Required test dimensions

| Dimension | Wrapper-only | Hook-enhanced |
|-----------|--------------|---------------|
| Bootstrap loads required files | Yes | Yes |
| `/yoke idea` files an item | Yes | Yes |
| `/yoke do` constructs a session offer with correct identity | Yes | Yes |
| `/yoke do` routes to a supported downstream path | Yes | Yes |
| `/yoke do` falls back for an unsupported downstream path | Yes | Yes |
| Lint hooks fire on Bash commands | N/A | Yes |
| Post-processing hooks fire on Bash commands | N/A | Yes |

### Test approach

- Wrapper-only tests verify correctness without any hook infrastructure.
- Hook-enhanced tests verify that hooks fire and produce expected side effects, but also verify that removing hooks does not break correctness.
- The test matrix should be runnable as a shell script or test suite, not just a manual checklist.

---

## Canonical Downstream Path Vocabulary

The canonical downstream paths are delivery lanes that `/yoke do` can route into. These values live in the shared Yoke registry:

| Path | Description | What it routes to |
|------|-------------|-------------------|
| `advance` | Move an item through the delivery lifecycle | `/yoke advance YOK-N [status]` |
| `shepherd` | Drive an item through quality-gated lifecycle to planned | `/yoke shepherd YOK-N` |
| `refine` | Critique and improve item artifacts | `/yoke refine YOK-N` |
| `conduct` | Engineer/Tester execution loop for a single item or epic | `/yoke conduct YOK-N` |
| `polish` | Review and finish implementation in existing worktree lane(s) | `/yoke polish YOK-N` |
| `usher` | Merge and deploy implemented items | `/yoke usher [YOK-N]` |

These path names are stable identifiers, not command strings. A harness declares disabled path identifiers only when its substrate cannot support a shared path; it does not copy the whole path list into its manifest. The routing layer maps path names to the corresponding operator commands.

Additional downstream paths may be added later. The vocabulary is intentionally narrow to avoid false parity claims.

---

## Adapter-Author Checklist

Use this checklist when creating a new harness adapter.

- [ ] **Bootstrap loader implemented.** The adapter loads all required files from the [Harness Bootstrap Contract](harness-bootstrap.md) section 1 via at least one mechanism (wrapper command, hook, or harness-native config).
- [ ] **Capability manifest defined.** A JSON manifest matching the schema above exists for this harness, with all required fields populated.
- [ ] **`harness_id` is unique.** No other adapter uses the same `harness_id`.
- [ ] **`supports.command_source` is shared.** Yoke-owned harnesses use `"shared_yoke_registry"` and do not copy command/path lists into the manifest.
- [ ] **Manifest limitations are truthful.** Every disabled entrypoint or downstream path names a concrete substrate limitation. No aspirational support or vague unsupported-by-default posture.
- [ ] **`telemetry.canonical_source` is `"yoke_core"`.** Harness-local telemetry is optional, never canonical.
- [ ] **Session-offer builder passes truthful identity and support data.** The adapter's offer call includes `--executor`, `--provider`, `--model`, `--workspace`, and `--session-id`; it passes `--supported-paths` only when the adapter does not rely on Yoke-core registry derivation.
- [ ] **Route wrapper respects registry + limitations.** The wrapper presents shared commands and produces a clear fallback response for manifest-disabled paths.
- [ ] **Wrapper-only mode works.** All correctness-critical behavior works without hooks. Hooks are opt-in enhancements.
- [ ] **Hook-enhanced mode is gated.** If the adapter uses hooks, they are gated by runtime/version checks. Missing hooks degrade to wrapper-only mode silently.
- [ ] **Smoke-test matrix passes.** Both wrapper-only and hook-enhanced columns pass for all applicable test dimensions.
- [ ] **No Yoke core modifications.** The adapter fits entirely within this template's five parts. No changes to Yoke core scripts, skills, or DB schema are required for the adapter itself.
- [ ] **No Tier 3 raw-entrypoint invocations.** The adapter never calls lower-level DB routers, event emitters, or other internal Python entrypoints directly.
