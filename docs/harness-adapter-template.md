# Harness Adapter Template (internal)

*Reusable template for integrating a new harness with Yoke. Every adapter must implement the required parts described below. The [Harness Bootstrap Contract](harness-bootstrap.md) defines the neutral startup expectations that every adapter loads.*

## Overview

A harness adapter is a thin layer between a specific agent runtime (Claude Code, Codex, Cursor, another harness) and Yoke's core operator interface. The adapter does not contain business logic -- it translates harness-native mechanisms (hooks, config files, CLI wrappers) into Yoke's neutral contract surface.

Every adapter must implement these parts:

1. **Bootstrap Loader** -- loads the Yoke-owned startup contract
2. **Capability Manifest** -- declares identity and supported paths
3. **Session Registration** -- binds session identity and delivers the launch mandate
4. **Route Wrapper** -- invokes only declared-supported Yoke commands
5. **Smoke-Test Matrix** -- validates both wrapper-only and hook-enhanced modes

Adding a harness also requires verifying the shared executor vocabulary,
manifest renderer, adapter capability, native identity/container mapping,
process classification, hook decisions/dispatch, project installation and
applicable doctor/render checks. Existing Claude Code, Codex and Cursor
implementations are source references. The [Cursor substrate evidence](harness-cursor-assessment.md)
retains dated probes; current owner and field authority lives in the
[manifest schema](../runtime/harness/manifest-schema.md).

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

### Schema and owners

Use the complete [manifest schema](../runtime/harness/manifest-schema.md) and
`yoke_core.domain.agents_render_manifests` renderer; do not instantiate a copied
partial schema. The current manifests under `runtime/harness/` are executable
examples, including surface-specific session control, launch-model encoding,
wake/turn recording, command workdir, hook enablement and canonical agent
consumption. Required fields and version floors remain schema-owned.

| Contract | Adapter obligation |
|---|---|
| `harness_id` / `identity` | Unique canonical executor; truthful provider/model/workspace sources and family normalization. |
| `runtime_minimums` | Separate wrapper-only and hook-enhanced floors; measured build is informational. |
| `bootstrap` | Name the executable spec and actual native delivery mechanisms. |
| `supports` | `command_source: shared_yoke_registry`; declare only concrete disabled entrypoints/paths and actual optional affordances. |
| `session_control` and wake/turn contracts | Declare each CLI/desktop surface's actual creation, injection, resume, ending, observation and wake behavior; no borrowed harness claims. |
| `telemetry` | Canonical source is `yoke_core`; local hook/transcript logs are informational. |
| Hook and agent consumption | Declare native config, trust/byte constraints, identity export, omissions and generated/native consumption truth. |

### Entrypoints vs downstream paths

The shared registry distinguishes two kinds of Yoke surfaces:

- **Entrypoints** are top-level `/yoke` operator commands (Tier 1 in the [bootstrap contract](harness-bootstrap.md) section 3). Yoke-owned harnesses inherit these commands from shared Yoke code unless their manifest declares a concrete limitation.

- **Downstream paths** name delivery capabilities declared by the shared registry and limited by each harness manifest. Staffing selects an item entrypoint from its pinned workflow binding.

A harness with `command_source: "shared_yoke_registry"` inherits the shared operator and downstream surfaces. If a substrate cannot support one of those surfaces, declare the matching `disabled_entrypoints` or `disabled_downstream_paths` entry and document the limitation. Work requiring a disabled downstream path falls back rather than failing silently.

### Shared registry plus manifest limitations

For harnesses with a manifest, Yoke core derives the effective `downstream_paths` server-side from the shared registry and then applies limitations from the coarse harness manifest. Surface-specific executor values normalize back to the family manifest (`codex-desktop` -> `runtime/harness/codex/manifest.json`, `claude-vscode` -> `runtime/harness/claude/manifest.json`). The shared registry is the command/path source; the manifest declares limitations and affordances.

**Shared Yoke code is the command/path source of truth for Yoke-owned harnesses.** Adapters declare concrete limitations in their manifests.

---

## Part 3: Session Registration

The opening hook registers the harness identity, including the workspace the
manifest's `workspace_source` names. A launched session then binds to its
launch mandate: in that same hook when the harness names the session before it
starts, or moments later when the vendor assigns the id and the relay matches
the session by machine, surface, and workspace. Read the registered identity
through `yoke sessions identity`; the launch's registered session must match
before its assigned work begins, and an empty registration whose
`identity_correlation` is still `pending` or `awaiting_registration` is in
flight, not a mismatch.

### Requirements

- Resolve identity from the harness-native session channel.
- Declare identity sources and limitations in the manifest.
- Preserve requested model facts separately from provider-attested served facts.
- Deliver and acknowledge the launch's exact mandate before claiming its item.

---

## Part 4: Route Wrapper

The route wrapper provides bootstrap and identity guidance for shared Yoke commands, then lets Yoke core own command execution semantics.

### Requirements

- Accept an explicit operator instruction or the launch mandate.
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
| Lint hooks fire on Bash commands | N/A | Yes |
| Post-processing hooks fire on Bash commands | N/A | Yes |

### Test approach

- Wrapper-only tests verify correctness without any hook infrastructure.
- Hook-enhanced tests verify that hooks fire and produce expected side effects, but also verify that removing hooks does not break correctness.
- Execute the smoke matrix through Python-owned tests; a checklist alone is not proof.

---

## Canonical Downstream Path Vocabulary

The canonical downstream paths describe shared delivery capabilities. These values live in the shared Yoke registry:

| Path | Description | What it routes to |
|------|-------------|-------------------|
| `implement` | Implement an issue through its review loop | `/yoke implement YOK-N` |
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
- [ ] **Capability manifest defined.** A JSON manifest matching the authoritative manifest schema exists for this harness, with all required fields populated.
- [ ] **`harness_id` is unique.** No other adapter uses the same `harness_id`.
- [ ] **`supports.command_source` is shared.** Yoke-owned harnesses use `"shared_yoke_registry"` and do not copy command/path lists into the manifest.
- [ ] **Manifest limitations are truthful.** Every disabled entrypoint or downstream path names a concrete substrate limitation. No aspirational support or vague unsupported-by-default posture.
- [ ] **`telemetry.canonical_source` is `"yoke_core"`.** Harness-local telemetry is optional, never canonical.
- [ ] **Session registration passes truthful identity and model facts.** Startup hooks register automatically; launch workers read and acknowledge the exact mandate before claiming its item.
- [ ] **Route wrapper respects registry + limitations.** The wrapper presents shared commands and produces a clear fallback response for manifest-disabled paths.
- [ ] **Wrapper-only mode works.** All correctness-critical behavior works without hooks. Hooks are opt-in enhancements.
- [ ] **Hook-enhanced mode is gated.** If the adapter uses hooks, they are gated by runtime/version checks. Missing hooks degrade to wrapper-only mode silently.
- [ ] **Smoke-test matrix passes.** Both wrapper-only and hook-enhanced columns pass for all applicable test dimensions.
- [ ] **Shared owners verified.** Vocabulary, native identity, adapter/render/install and doctor changes agree; preserve shared workflow and state semantics.
- [ ] **No Tier 3 raw-entrypoint invocations.** The adapter never calls lower-level DB routers, event emitters, or other internal Python entrypoints directly.
