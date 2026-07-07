## Objective

Refine `YOK-1227` into a buildable first slice for Codex without over-promising harness portability or Codex parity.

The design must produce one truthful early cross-harness lane while keeping Yoke core as the canonical owner of workflow truth.

## Supporting research

If the implementor needs the observed Codex-hook behavior behind this plan, see:

- `yoke/context-archive/2026-04-03-yok-1227-codex-hook-spike.md`

That memo now captures both:

- the earlier false-negative run on an older app-bundled Codex build
- the successful retest on the updated app-bundled `0.118.0-alpha.2` build

## Research-based constraints

### Constraint 1: Codex hooks are version-gated, not universally available

As of April 3, 2026:

- hook support is still experimental and build-sensitive
- an older app-bundled `0.115.0-alpha.27` build only proved `SessionStart`
- the updated app-bundled `0.118.0-alpha.2` build proved `SessionStart`, `UserPromptSubmit`, `PreToolUse`, and `PostToolUse` in `codex exec`
- therefore any hook-dependent behavior in this slice must declare a minimum Codex version and degrade safely when unavailable

### Constraint 2: Codex Bash hooks are usable, but still non-canonical

On the updated local build:

- `PreToolUse` and `PostToolUse` fired with `matcher: "Bash"`
- the payloads included `tool_name`, `tool_input.command`, `tool_use_id`, and `tool_response`
- short commands and a `sleep 3; echo ...` command both emitted pre/post events in `codex exec`

That is good enough for:

- bootstrap ergonomics
- prompt-time guidance
- optional local hook-driven observations
- a cheap first-pass parity slice for the tested hook subset: `SessionStart`, `UserPromptSubmit`, `PreToolUse`, and `PostToolUse`

It is still not sufficient to become the canonical source of truth for workflow routing, ownership, or official Yoke telemetry.

### Constraint 3: Bootstrap and telemetry must be separated

Codex may help load startup instructions, but Yoke core must remain responsible for:

- session offers
- support declarations
- routing decisions
- fallback decisions
- claim / ownership truth once `YOK-1221` is in place
- canonical ledger events

### Constraint 4: Codex is the first proving adapter, not the rule

The contract must be harness-neutral. Codex-specific logic is allowed only in thin bootstrap and wrapper layers.

### Constraint 5: The first slice should define a reusable harness-adapter template

Because hook availability is version-gated and optional affordances differ by harness, the first slice should define a reusable harness-adapter template rather than hardcoding one-off Codex behavior.

### Constraint 6: Scope must follow Yoke's real hook usage, not abstract Claude coverage

The meaningful target is the hook behavior Yoke actually relies on today:

- main-session startup orientation via `UserPromptSubmit -> harness-session-start.sh`
- main-session Bash preflight guardrails via `PreToolUse(Bash)` for:
  - `lint-sqlite-cmd.sh`
  - `lint-event-registry.sh`
  - `lint-main-commit.sh`
  - `lint-test-pipe.sh`
  - Bash-side `lint-tc-label.sh`
  - `observe-tool-pre.sh`
- main-session Write-specific checks via `PreToolUse(Write)` for:
  - `lint-write-path.sh`
  - Write-side `lint-tc-label.sh`
  - `observe-tool-pre.sh`
- main-session Bash post-processing via `PostToolUse(Bash)` for:
  - `sqlite3-error-hook.sh`
  - `observe-tool.sh --hook-event PostToolUse`
- main-session non-Bash telemetry via `PostToolUse` / `PostToolUseFailure` on `Write`, `Edit`, and `Read`
- subagent stop safety-net behavior via `SubagentStop -> on-agent-stop.sh` on all 7 Yoke agents
- agent-scoped Bash completion handling via `on-bash-complete.sh` on Engineer only

This means the first Codex slice should:

- port the Yoke behaviors that map directly onto Codex's tested hook surface
- keep the Yoke behaviors that do not have a Codex hook equivalent in the adapter or Yoke core
- explicitly avoid pretending that Claude-only `Write` / `Edit` / `Read` hook coverage has a direct Codex match today

## Proposed slice

### 1. Define a Yoke-owned bootstrap contract

Create one shared startup contract for non-Claude harnesses that states:

- the required always-do-first reads
- the safe top-level Yoke operator commands
- the distinction between top-level commands and internal scripts
- the expectations for session identity, support declaration, and fallback

This contract should be Yoke-owned, not trapped in `.claude`-only guidance.

### 2. Define a reusable harness-adapter template

The first slice should define a reusable adapter template with five required parts:

1. **Bootstrap loader**
   - loads the Yoke-owned startup contract
   - works without hooks
   - may optionally use a session-start hook when available
2. **Capability manifest**
   - declares harness identity
   - declares supported Yoke entrypoints
   - declares supported downstream Yoke paths
   - declares optional local affordances such as startup hooks and Bash tool hooks
3. **Session-offer builder**
   - translates runtime identity plus declared support into the Yoke core offer format
4. **Route wrapper**
   - invokes only the top-level Yoke commands or downstream paths the manifest explicitly supports
5. **Smoke-test matrix**
   - validates wrapper-only mode
   - validates hook-enhanced mode when the harness/runtime supports it

### 3. Add a thin Codex bootstrap adapter

Codex gets a thin adapter that can load the shared bootstrap contract in one of two ways:

- preferred ergonomic path: repo-local `SessionStart` hook that injects bootstrap instructions
- required safe path: an explicit wrapper/entry command that loads the same Yoke-owned bootstrap contract even if hooks are absent or disabled

The system must remain safe if the hook is missing or the Codex version is too old for the desired hook event.

### 4. Keep the initial Codex command surface intentionally narrow

The first Codex proving slice should only claim support for:

- safe entry via `/yoke idea`
- safe entry via `/yoke do`
- one explicit review/polish lane that needs only a small downstream Yoke command surface

It must not imply blanket parity for every Yoke command.

### 5. Add explicit support declaration to the Codex adapter

The Codex adapter must identify:

- harness identity
- workspace
- model/provider identity
- supported top-level Yoke entrypoints
- supported downstream Yoke paths for the chosen proof lane
- optional local affordances actually available in the running build, such as:
  - `session_start_hook`
  - `user_prompt_submit_hook`
  - `bash_pre_tool_hook`
  - `bash_post_tool_hook`

This support declaration is how Yoke decides whether Codex can take the next step.

### 6. Put all routing and fallback in Yoke core

`/yoke do` should consume the support declaration and:

- route work only when the downstream path is supported
- fall back truthfully when it is not
- never imply Codex parity beyond the declared support set

### 7. Keep telemetry core-owned

For the first slice, telemetry should come from Yoke-owned paths:

- `SessionOffered`
- `NextActionChosen`
- and, once `YOK-1221` lands first, ownership lifecycle events such as registration, claim, release, and end

Codex hook output may be recorded locally or used for operator ergonomics, but it is not the required canonical telemetry source in the first slice.

### 8. Use Codex hooks as optional enhancements, not as the only safety layer

On builds that support them, a repo-local Codex hook pack may do three useful things:

- inject bootstrap/orientation context
- augment prompt-time guidance
- provide optional local visibility into Bash tool use

For `YOK-1227`, the low-hanging-fruit hook subset is now explicit:

- `SessionStart`
- `UserPromptSubmit`
- `PreToolUse`
- `PostToolUse`

That tested subset should be treated as in-scope for hook-enhanced Codex mode on supported builds.

Its job is still not:

- enforce all routing policy
- emit canonical telemetry
- block unsafe work as the sole safety layer

### 9. Add a version-gated Codex mode split

The Codex adapter should explicitly support two operating modes:

- **wrapper-only mode**
  - works on older Codex builds
  - depends only on the explicit wrapper/entry command
- **hook-enhanced mode**
  - requires a Codex build that supports the desired hook events
  - may use `SessionStart`, `UserPromptSubmit`, `PreToolUse`, and `PostToolUse`

The first slice should be safe in wrapper-only mode and nicer in hook-enhanced mode.

### 10. Port only the Yoke hook behaviors that map cleanly

For `YOK-1227`, the first Codex adapter should treat Yoke's current hook usage like this:

- **Directly portable as Codex hooks**
  - startup orientation
  - prompt-time guidance
  - Bash preflight guardrails
  - Bash pre-tool timing markers
  - Bash post-tool recovery/guidance
  - Bash post-tool progress or debug breadcrumbs
- **Must stay adapter-owned or core-owned**
  - canonical session lifecycle truth
  - `AgentSessionStopped` / stopped-state recovery behavior
  - canonical `ToolCallFailed` recording
  - routing truth
  - fallback truth
  - ownership truth
- **Should not be claimed as Codex-hook parity in this slice**
  - `Write`-tool-specific guardrails such as `lint-write-path.sh`
  - `Write` / `Edit` / `Read` telemetry parity
  - Claude-specific write/edit block hooks on read-only Yoke agents
  - any behavior that depends on Claude exposing non-Bash tool hooks

## Reusable harness-adapter template

Each harness should fit this manifest shape conceptually:

```json
{
  "harness_id": "codex",
  "runtime_minimums": {
    "wrapper_only": "any supported runtime",
    "hook_enhanced": "codex >= 0.117.0",
    "tested_locally": "0.118.0-alpha.2"
  },
  "bootstrap": {
    "required_reads": [
      "CLAUDE.md",
      ".claude/rules/session.md",
      "git log --oneline -10",
      "yoke/BOARD.md"
    ],
    "mechanisms": [
      "wrapper_command",
      "optional_session_start_hook"
    ]
  },
  "identity": {
    "executor": "codex",
    "provider_source": "runtime",
    "model_source": "runtime",
    "workspace_source": "git_root"
  },
  "supports": {
    "entrypoints": [
      "/yoke idea",
      "/yoke do"
    ],
    "downstream_paths": [
      "review_polish_v1"
    ],
    "optional_local_affordances": [
      "session_start_hook",
      "user_prompt_submit_hook",
      "bash_pre_tool_hook",
      "bash_post_tool_hook"
    ]
  },
  "telemetry": {
    "canonical_source": "yoke_core",
    "optional_local_sources": [
      "hook_logs"
    ]
  },
  "fallback": {
    "when_hooks_missing": "wrapper_only",
    "when_path_unsupported": "return unsupported to core"
  }
}
```

And each concrete harness adapter should ship this checklist:

- one wrapper that works even if hooks are absent
- one manifest declaring exactly what the harness supports
- one offer-builder that translates the manifest into Yoke-core routing input
- one optional hook pack that can be enabled only when the harness/runtime supports it
- one smoke-test matrix covering wrapper-only mode and hook-enhanced mode

## Codex-specific first instantiation

For Codex, the first useful harness instantiation should be:

- wrapper-only safe entry for `/yoke idea` and `/yoke do`
- hook-enhanced bootstrap via `SessionStart`
- hook-enhanced prompt guidance via `UserPromptSubmit`
- hook-enhanced Bash preflight guardrails and timing via `PreToolUse`
- hook-enhanced Bash post-run recovery, progress breadcrumbs, and optional local observations via `PostToolUse`
- version-gated parity for that tested four-hook subset relative to the Yoke behaviors we currently rely on most
- adapter-owned or core-owned handling for the Yoke behaviors with no Codex hook equivalent, especially:
  - stop / session-end recovery
  - failure recording
  - canonical telemetry
- no dependence on hook output for canonical Yoke truth

## Tested hook parity map

The first slice should treat this as the explicit Codex hook-parity target:

| Codex hook | Yoke behavior it can help cover | Allowed role in first slice | Must not own |
|---|---|---|---|
| `SessionStart` | startup orientation / always-do-first guidance | inject bootstrap context and point Codex at the Yoke-owned startup contract | canonical session truth |
| `UserPromptSubmit` | prompt-time operator guidance | remind Codex to prefer safe top-level Yoke commands and the wrapper path | routing policy or correctness enforcement |
| `PreToolUse` | Bash preflight guardrails and timing | run portable Bash-only Yoke preflight hooks and timing markers before Codex Bash executes | canonical approval / routing / ownership decisions |
| `PostToolUse` | Bash post-run recovery, progress breadcrumbs, and local observation | inject Bash-result guidance such as sqlite failure correction, run Bash completion helpers, and attach local debugging breadcrumbs | canonical telemetry or proof of workflow completion |

This is the intended parity boundary for `YOK-1227`.

Anything beyond that four-hook subset is future work, not low-hanging fruit for this ticket.

## Yoke hook behavior map for Codex

This is the operator-relevant map of what Yoke should actually try to port in `YOK-1227`:

| Yoke behavior today | Current Claude hook path | Codex implementation target | First-slice stance |
|---|---|---|---|
| startup orientation | `UserPromptSubmit -> harness-session-start.sh` | `SessionStart` primarily, `UserPromptSubmit` secondarily | port |
| Bash DB / command guardrails | `PreToolUse(Bash)` lints | `PreToolUse(Bash)` | port |
| pre-tool timing markers | `PreToolUse -> observe-tool-pre.sh` | `PreToolUse(Bash)` for Bash timing only | port |
| Bash sqlite failure correction | `PostToolUse(Bash) -> sqlite3-error-hook.sh` | `PostToolUse(Bash)` | port |
| engineer Bash completion side effects | `PostToolUse(Bash) -> on-bash-complete.sh` | `PostToolUse(Bash)` | port when Codex is running the matching Engineer-style lane |
| tool success telemetry | `PostToolUse -> observe-tool.sh` | Bash-only local hook breadcrumbs plus Yoke-core canonical events | partial |
| tool failure telemetry | `PostToolUseFailure -> observe-tool.sh` | adapter/core handling, optionally aided by Bash post-hook inspection | adapter/core |
| stop / crash recovery | `SubagentStop -> on-agent-stop.sh` | adapter/core session-stop handling | adapter/core |
| Write path safety | `PreToolUse(Write) -> lint-write-path.sh` | no direct Codex hook equivalent | do not claim parity |
| Write/Edit/Read telemetry | `PostToolUse` / `PostToolUseFailure` on non-Bash tools | no direct Codex hook equivalent | do not claim parity |
| read-only agent write/edit block hooks | `PreToolUse(Write/Edit)` block hooks on Tester/Simulator/Boss | manifest/tool-surface restriction, not Codex hooks | adapter/core |

## Planned artifacts

1. A Yoke-owned harness bootstrap contract doc
2. A reusable harness-adapter template / manifest definition
3. A Codex-specific thin bootstrap wrapper over that contract
4. A Codex support-declaration surface consumed by `/yoke do`
5. An optional Codex hook pack gated by runtime/version support
6. A small hook-parity map for the tested Codex subset versus the Yoke/Claude expectations it is meant to cover
7. Core routing updates so `/yoke do` uses support declarations plus truthful fallback
8. A proof script/test matrix for `/yoke idea`, `/yoke do`, and one explicit review/polish lane in both wrapper-only and hook-enhanced modes

## Non-goals for this slice

- full Codex parity with Claude
- full hook duplication beyond the tested `SessionStart` / `UserPromptSubmit` / `PreToolUse` / `PostToolUse` subset
- parity claims for Yoke's Claude-only `Write` / `Edit` / `Read` hook behavior
- Codex-owned canonical telemetry
- broad skill-substrate migration
- broad extraction of every `.claude` path into a new universal harness layer
- full portability across every future harness

## Sequencing

1. Land `YOK-1221` first so ownership truth exists
2. Add the Yoke-owned neutral bootstrap contract
3. Define the reusable harness-adapter template / manifest shape
4. Add the thin Codex bootstrap adapter
5. Add support declaration plus `/yoke do` fallback logic
6. Add the optional Codex hook pack with explicit version gating
7. Add the tested four-hook parity map and wire the supported subset into hook-enhanced Codex mode
8. Prove `/yoke idea`, `/yoke do`, and one review/polish lane in wrapper-only mode and hook-enhanced mode
9. Leave full telemetry follow-through to `YOK-1187`

## Validation

The first slice is complete only when:

1. Codex can load the shared startup expectations through a thin adapter
2. Codex can safely enter through `/yoke idea` and `/yoke do`
3. Yoke core can tell which downstream path Codex supports
4. Unsupported work falls back cleanly
5. Wrapper-only mode remains safe when hook affordances are unavailable
6. Hook-enhanced mode works on a supported Codex build with `SessionStart`, `UserPromptSubmit`, `PreToolUse`, and `PostToolUse`
7. The tested four-hook subset is explicitly mapped to the Yoke behaviors it is meant to cover
8. The proof lane does not rely on hook output for correctness
9. The canonical trace comes from Yoke core, not from Codex-local hook telemetry
10. The plan does not claim direct Codex parity for Yoke's `Write` / `Edit` / `Read` hook behaviors
