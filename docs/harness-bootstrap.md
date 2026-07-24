# Harness Bootstrap Contract

*Yoke-owned neutral bootstrap contract for any harness. This document defines what every harness must do at session startup and how Yoke surfaces are classified for harness-facing use.*

## 1. Startup Reads

Every harness must load the startup reads defined in the neutral bootstrap spec at `runtime/harness/bootstrap-spec.json`, regardless of whether the harness uses hooks to inject them or loads them via an explicit wrapper command.

That JSON file is the executable source of truth for bootstrap content. This document is the human contract that explains how harnesses must consume it.

### Bootstrap spec shape

| Field | Meaning | Notes |
|------|---------|-------|
| `required_files` | Ordered Yoke-owned docs that every harness must load | Includes the shared prompt doctrine; harness-specific shell docs are separate thin wrappers |
| `required_commands` | Ordered shell commands whose output every harness must load | Recent commit context and current branch identity |
| `recommended_files` | Additional reads when present | Auto-generated views and recurring-pattern docs that improve cold-start context |

### What the spec covers

- Project rules and conventions
- Critical runtime invariants that must be inlined into startup context,
  including canonical DB path resolution from worktrees
- Architecture and command-surface orientation
- The bootstrap contract itself
- The shared prompt doctrine (`Be the giant`)
- Recent commit and branch context
- Optional board/pattern reads when available

### Bootstrap mechanism

A harness may load startup reads through any of these mechanisms:

1. **Hook-injected:** A session-start hook reads and injects the required files (e.g., Claude Code's `UserPromptSubmit` hook routed through `yoke hook evaluate UserPromptSubmit`, or Codex's `SessionStart` hook routed through `yoke hook evaluate SessionStart`).
2. **Wrapper command:** An explicit entry command loads the same files before the first operator interaction.
3. **Harness-native config:** The harness's own configuration mechanism includes the files and commands defined by the bootstrap spec in the system prompt or context window.

The mechanism does not matter. The content does. A harness that has loaded all required files and commands is bootstrapped regardless of how it got there.

### Generated `main_agent` packet

The shared bootstrap render path (`runtime.harness.bootstrap.render_compact` and `render_full`) injects the layer-explicit `main_agent` packet block via [`yoke_core.domain.main_agent_packet`](../packages/yoke-core/src/yoke_core/domain/main_agent_packet.py). The block is generated, never hand-copied: the body comes from `yoke_core.domain.schema_api_context.render_role_packet("main_agent")` and stays in lockstep with subagent packets via the schema/API-context drift check.

The injection means the top-level Yoke session sees the same compact `core` + `claims` spine the read-only subagents (`architect_agent`, `simulator_agent`, `boss_agent`) see, alongside the file-reads list and Critical Runtime Invariants block. Harnesses that consume the shared bootstrap render path (via `runtime.harness.hook_runner` for both Codex and Claude Code) inherit the packet automatically.

If the schema/API context generator is unavailable (fresh checkout, broken bootstrap state), the bootstrap path stays fail-open: the helper returns an empty block and the orientation continues with file-reads + invariants only. There is no path that hand-copies stale packet content into the orientation prose.

## 1a. Layer Names: `main_agent` vs. `harness_contract`

Yoke packet vocabulary is layer-explicit and does not mix LLM-facing schema/API context with the substrate manifest contract. Two layer names matter for harness adapters and operator docs:

- **LLM-facing packet layer** — `main_agent`, `architect_agent`, `engineer_agent`, `tester_agent`, `simulator_agent`, `boss_agent`. These are the role keys in `yoke_core.domain.schema_api_context_seed.ROLE_TOPICS`. The renderer expands marker pairs in canonical agent prompts (`runtime/agents/<role>.md`) using these names; the bootstrap path injects the `main_agent` block via `yoke_core.domain.main_agent_packet`.
- **Substrate contract layer** — `harness_contract`. This name covers manifest- and bootstrap-derived substrate capability truth: hooks, env / session identity, cwd binding, adapter render format, supported commands, disabled paths, known parity limits. It lives in this file (`docs/harness-bootstrap.md`) and in the per-harness manifest schema documented at [`runtime/harness/manifest-schema.md`](../runtime/harness/manifest-schema.md). `harness_contract` is deliberately NOT a `schema_api_context` role; the renderer does not produce a packet body for it.

The two layers are kept separate so an LLM packet referring to `harness_contract` content (or vice versa) is structurally invalid. Adding a new harness adapter means writing or updating the harness's `manifest.json` and `manifest-schema.md` entry under `harness_contract`, not adding a new `schema_api_context` role.

## 2. Safe Operator Commands

These are the top-level `/yoke` commands that constitute the safe operator interface. Any harness may invoke these commands. They are the only sanctioned entry points for external harness interaction with Yoke.

| Command | Description | Entry safety |
|---------|-------------|--------------|
| `/yoke idea {title}` | Capture a new backlog item | Safe: creates only, no destructive side effects |
| `/yoke shepherd YOK-N` | Drive item through quality-gated lifecycle to planned | Safe: orchestrates worker agents through defined transitions |
| `/yoke conduct YOK-N` | Engineer/Tester loop for a single item or epic | Safe: scoped to the item's implementation worktree lane set |
| `/yoke advance YOK-N implementation` | Issue implementation entry — opens worktree and starts the implementation/review loop | Safe: scoped to a single item, creates worktree on entry |
| `/yoke usher [YOK-N]` | Merge and deploy implemented items | Safe: operates on implemented items only, requires operator confirmation |
| `/yoke doctor [project]` | Health checks and diagnostics | Safe: read-only by default, `--fix` requires explicit opt-in |
| `/yoke freeze YOK-N` | Freeze an item | Safe: sets frozen flag only |
| `/yoke thaw YOK-N` | Thaw a frozen item | Safe: clears frozen flag only |
| `/yoke block YOK-N "<reason>"` | Mark an item blocked with operator-supplied reason | Safe: sets blocked flag and reason only, preserves lifecycle status |
| `/yoke unblock YOK-N` | Clear an item's blocked flag and reason | Safe: clears blocked flag only, preserves lifecycle status |
| `/yoke resync` | Detect and repair GitHub drift | Safe: `--fix` requires explicit opt-in |
| `/yoke curate` | Curate the Ouroboros learning log | Safe: processes observations, proposes tickets |
| `/yoke wrapup` | Structured session wrap-up | Safe: captures reflections and session summary |
| `/yoke refine YOK-N` | Critique and improve item artifacts | Safe: structured-field refinement only, no worktree or code edits |
| `/yoke polish YOK-N` | Review and finish implementation in existing worktree lane(s) | Safe: scoped to one item's recorded implementation lanes and explicit verification |
| `/yoke help` | Show command reference | Safe: read-only |
| `/yoke do` | Autonomous session orchestrator | Safe: offers session to decision engine, routes to chosen mode |
| `/yoke charge` | Pick up next runnable item from frontier | Safe: confirms with operator before dispatch |
| `/yoke feed` | Refresh stale frontier items, reconcile frontier facts, and materialize strategy-backed work | Safe: updates structured item fields, creates idea records, refreshes dependency graph |
| `/yoke strategize` | Guided Strategic Markdown Layer review | Safe: multi-checkpoint interactive loop with operator approval at each stage |

## 3. Command Classification

Yoke surfaces are classified into three tiers. The tier determines whether a harness should invoke a surface directly.

### Tier 1: Top-level operator commands

These are the commands listed in section 2 above. They are the sanctioned external interface. Every harness should use only these commands for Yoke interaction.

**Examples:**

- `/yoke idea` -- create a new backlog item
- `/yoke do` -- autonomous session orchestrator
- `/yoke shepherd YOK-N` -- drive item through lifecycle
- `/yoke conduct YOK-N` -- Engineer/Tester execution loop
- `/yoke advance YOK-N implementation` -- issue implementation entry (opens worktree)
- `/yoke usher [YOK-N]` -- merge and deploy
- `/yoke doctor [project]` -- health checks
- `/yoke freeze YOK-N` -- freeze item
- `/yoke thaw YOK-N` -- thaw item
- `/yoke block YOK-N "<reason>"` -- block item (lifecycle status preserved)
- `/yoke unblock YOK-N` -- unblock item
- `/yoke resync` -- repair GitHub drift
- `/yoke curate` -- Ouroboros curation
- `/yoke wrapup` -- session wrap-up
- `/yoke refine YOK-N` -- artifact refinement
- `/yoke polish YOK-N` -- finishing review in existing worktree lane(s)
- `/yoke help` -- command reference
- `/yoke charge` -- frontier execution
- `/yoke feed` -- strategy materialization and frontier-fact maintenance
- `/yoke strategize` -- SML review

### Tier 2: Internal sub-skills

These are called by operator commands or other sub-skills. They have SKILL.md files and can technically be invoked directly, but they are not part of the primary operator interface. A harness should not invoke these directly unless it is implementing a specific downstream path that Yoke core has routed to it.

`/yoke advance` is dual-classified: the `implementation` form (`/yoke advance YOK-N implementation`) is the operator-facing issue implementation entry above. Other advance targets (e.g. `reviewing-implementation`, `reviewed-implementation`) and the bare `/yoke advance YOK-N [status]` form are still internal sub-skill calls invoked by `conduct`, `usher`, `do`, and routed dispatch.

| Sub-skill | Called by | Purpose |
|-----------|----------|---------|
| `/yoke advance YOK-N [status]` | conduct, usher, do/loop, routed dispatch | Internal advance targets other than `implementation` |
| `/yoke merge {epic-id}` | usher | Sequential PR + CI + merge per branch |
| `/yoke approve YOK-N` | usher | Approve a deployment stage |
| `/yoke amend {epic-id}` | conduct | Add, split, reassign, or remove tasks |
| `/yoke plan {epic-id}` | shepherd, conduct | Architect planning: task decomposition |
| `/yoke simulate {epic-id}` | conduct | Cross-task integration gap detection |

### Tier 3: Raw internal Python entrypoints

These are internal implementation mechanisms. A harness must never invoke these directly. They are the plumbing beneath the operator commands and sub-skills.

**Examples of raw Python entrypoints (never invoke directly from a harness):**

- Direct item creation through the db-router internals -- use `/yoke idea` instead.
- Direct item updates through the db-router internals -- use the `items.structured_field.replace` / `items.scalar.update` function ids (see [`.yoke/docs/db-reference/functions.md`](db-reference/functions.md)) or the wrapped operator surface where one exists.
- `python3 -m yoke_core.cli.db_router query` -- source-dev/operator-debug raw SQL break-glass; everyday diagnostics use `yoke db read`
- Direct epic db-router operations -- operator/debug adapters for the `workflow_item.epic_task.*` and `workflow_item.epic_progress_note.append` function family.
- `yoke_core.domain.emit_event` -- internal event emitter module.
- `yoke board rebuild` -- operator/debug adapter that dispatches `board.rebuild.run`
- `yoke_core.engines.repair_status` / `yoke_core.domain.update_status` -- internal lifecycle transition modules (agent path: `lifecycle.transition`).
- Direct `yoke_core.api.service_client` session and claim adapters -- operator/debug fallbacks for session lifecycle, `db_claim.amend`, and claim families. Prefer wrapped `yoke claims work ...` and `yoke claims path ...` surfaces where they exist.
- `yoke_core.domain.worktree` -- internal worktree creation, resolution, and install module.
- `yoke_core.domain.item_field_transform` -- internal structured-field transform adapter for `items.structured_field.append_addendum` / `section_upsert` / `section_append`.
- Direct epic task body updates through `yoke_core.domain.epic` -- operator/debug adapter for `workflow_item.epic_task.body_replace`.

All zero-shell scripts that previously filled this role were retired in the zero-shell waves. The Python entrypoints above are the only sanctioned internal surfaces today, and the agent-facing mutation path runs through the Yoke function-call surface (`POST /v1/functions/call` plus the in-process dispatcher); the operator-readable Atlas of registered surfaces lives at [`docs/atlas.md`](atlas.md). External tooling (git, pytest, package managers, `rg` / `grep`) stays command-shaped under the permanent-boundary classification.

**Why this matters:** Raw internal entrypoints assume Yoke's invariants (DB state, lifecycle ordering, hook enforcement, event emission). Calling them directly from a harness bypasses the safety gates, lifecycle validation, and audit trail that operator commands provide. The result is corrupted state, missing events, and broken invariants.

## 4. Session Identity Expectations

When a harness connects to Yoke, Yoke needs to know certain facts about the session to make routing and fallback decisions. These identity fields are not required at bootstrap time, but must be available by the time `/yoke do` evaluates what work to route.

### Required identity fields

| Field | Description | Source |
|-------|-------------|--------|
| `executor` | The harness identity passed at session-offer time. Surface-specific values such as `claude-desktop`, `codex-vscode`, or `codex-cli` are accepted as input; Yoke canonicalizes the value at write time so `harness_sessions.executor` stores only `claude-code` or `codex`, and the original surface alias is preserved in `harness_sessions.executor_display_name` for operator-facing rendering. Surface-specific input continues to drive lane resolution via `executor_default_lane_<surface>` overrides. | Harness self-declaration |
| `provider` | The model provider (e.g., `anthropic`, `openai`) | Runtime or harness configuration |
| `model` | The specific model identifier (e.g., `claude-opus-4-7`, `o3-pro`) | Runtime or harness configuration |
| `workspace` | The git repository root path | `git rev-parse --show-toplevel` |
| `session_id` | A unique session identifier | Harness-generated canonical id. Supported harnesses (`claude-code`, `codex`) MUST pass their canonical session id; auto-generated fallbacks are rejected at the service boundary. |

### Optional identity fields

| Field | Description | Source |
|-------|-------------|--------|
| `supported_paths` | Which downstream Yoke paths this harness can execute | Yoke core derives this server-side from the shared registry plus any limitations in the coarse harness manifest. Surface-specific executors normalize back to the family manifest (`codex-desktop` -> `runtime/harness/codex/manifest.json`, `claude-vscode` -> `runtime/harness/claude-code/manifest.json`). Harness-passed values are ignored for Yoke-owned harnesses. Harnesses without a manifest fall into the backward-compat branch (empty list = all paths supported). |
| `hook_affordances` | Which hook events the harness supports | Harness capability manifest |
| `lane` | Execution lane identity (e.g., `DARIUS`) | Harness or operator configuration |

### Identity resolution

Yoke does not prescribe how a harness resolves these fields. The harness may:

- Read them from its own runtime environment
- Declare them in a static capability manifest
- Derive them from configuration files
- Report them dynamically at session offer time

The only requirement is that the values are truthful. Yoke uses these fields to decide what work to route and what to fall back on. False identity leads to failed routing.

### Session scratch cleanup

The stale-session lifecycle sweep also runs a machine-throttled scratch
janitor. It removes only known scratch artifact kinds whose ownership is
positively dead: a registered harness session must have a recorded end time,
while a non-harness `session-unknown` run must use a `pid-N` run id whose
process is no longer alive. Current, DB-active, unknown UUID, live-PID, and
unverifiable owners are preserved. PID liveness is checked again immediately
before deletion, and a machine lock prevents concurrent sweepers.

`/yoke doctor --fix` uses the same proof rules for operator-attended repair.
If the session registry is unavailable, automatic mutation fails closed; the
doctor reports the problem without treating filesystem age alone as ownership
proof.

For supported harnesses such as Claude Code and Codex, `session_id` should come from the harness runtime's stable conversation identifier (`CLAUDE_SESSION_ID`, `CODEX_THREAD_ID`, or a hook payload `session_id` when the env var is unavailable). Do not invent a second ID format for those harnesses.

### Path support and fallback

For supported harnesses, Yoke core derives the effective `supported_paths` server-side from the shared registry plus any limitations in the coarse harness manifest. Surface-specific executor values normalize back to their family manifest (`codex-desktop` -> `runtime/harness/codex/manifest.json`, `claude-vscode` -> `runtime/harness/claude/manifest.json`). Both `codex` and `claude-code` ship a manifest in the shared schema documented at [`runtime/harness/manifest-schema.md`](../runtime/harness/manifest-schema.md). Harnesses without a manifest fall into the backward-compat branch (empty list = all paths supported). Work requiring an unsupported downstream path falls back gracefully -- Yoke does not route unsupported work.

Non-Yoke-owned adapters may still declare `supported_paths` at session-offer time. If they omit the field and no manifest exists for the executor, Yoke preserves backward compatibility by treating the session as unconstrained for downstream-path validation. Adapters that want truthful fallback enforcement should add a manifest under `runtime/harness/{executor}/manifest.json` (or normalize their own surface-specific executors back to a family manifest the way Yoke-owned harnesses do); harness-passed `supported_paths` is ignored for Yoke-owned harnesses. Yoke-owned manifests should declare limitations, not copied command/path allowlists.

## 5. Repo-local Skill Discovery

Yoke skills live canonically in the **hidden** repo-local directory `.agents/skills/yoke/`. Modern Codex runtimes natively scan repo-local `.agents/skills` locations, so the Yoke skill tree is a first-class Codex skill source when Codex starts in this repository. No `.codex/skills` mirror is required.

Because the directory is hidden, generic discovery (e.g. `rg --files`, plain `ls`) still skips it unless the caller explicitly includes hidden paths. Wrapper-only harnesses, thin docs, and operator tooling therefore cannot guess the canonical location -- they must consume a Yoke-owned resolver.

### Canonical layout

- `.agents/skills/yoke/SKILL.md` — the root `/yoke` router skill.
- `.agents/skills/yoke/{name}/SKILL.md` — each direct subskill (`idea`, `shepherd`, `strategize`, etc.).
- `.agents/skills/yoke/{name}/*.md` — **phase sub-files** (e.g. `advance/preflight.md`). These are *not* standalone skills and are never returned by the discovery surface.
- `.agents/skills/yoke/{name}/{nested}/SKILL.md` — nested internal skills may be visible to Codex's native scanner even when Yoke's resolver hides them. They still use their own `SKILL.md` frontmatter as the shared metadata source.
- `.agents/skills/yoke/{scripts,shared}/` — supporting directories without a top-level `SKILL.md`. Discovery ignores them.

`.claude/skills/yoke` is a **compatibility symlink** that points at `../../.agents/skills/yoke`. Claude Code's built-in skill loader follows it, but wrappers, thin docs, and operator tooling must treat `.claude/skills/yoke/...` as compatibility-only — the canonical form is always the `.agents/...` path.

### Discovery surface

The `runtime.harness.bootstrap` module owns repo-local skill discovery.
Its `skill-list` mode enumerates available skills, and its `skill-path`
mode resolves one skill name to its canonical `SKILL.md` path. No
wrapped product CLI exists for this harness bootstrap resolver yet.

- `skill-list` enumerates top-level Yoke skill names from `.agents/skills/yoke/`. The first entry is always the root router skill (`yoke`). Each subsequent entry is a direct subdirectory that contains a `SKILL.md`. Phase sub-files and directories without a top-level `SKILL.md` are excluded.
- `skill-path <name>` returns the absolute canonical `.agents/...` `SKILL.md` path. For the root router skill, `skill-path yoke` returns `.agents/skills/yoke/SKILL.md`.
- Missing skills exit non-zero with a clear `not found at <canonical path>` message on stderr. The resolver never falls back to `~/.agents`, `~/.codex/skills`, or any home-directory guess — if the repo-local path is missing, the resolver fails loudly rather than silently resolving to a platform global.
- `--root` defaults to the current working directory when omitted. `--spec` is *not* required for the discovery modes; they operate purely against `.agents/skills/yoke/`.

### When to consume the resolver

| Caller | What to do |
|--------|-----------|
| Codex native skill loader | Let Codex scan `.agents/skills` directly; use `SKILL.md` frontmatter as the shared metadata source. |
| Wrapper-only harness bootstrap (e.g. `codex_entry bootstrap`) | Invoke the resolver to confirm the canonical tree exists before delegating to `/yoke` commands. |
| Thin docs that list available skills | Derive the list from `skill-list` instead of hardcoding, so the doc never drifts from the repo. |
| Operator shell commands composing a skill path | Call `skill-path` rather than concatenating `.agents/skills/yoke/<name>/SKILL.md` by hand. |
| Claude Code's native Skill tool | Continue to use the harness-owned loader; this contract is for repo-local wrapper discovery, not Claude Code's built-in skill surface. |

Harnesses that need a shell-native resolver should only introduce one when an actual current shell wrapper requires it. Symmetry with existing shell inventories is not enough justification -- the Python surface above is harness-neutral and works for Codex, Claude Code wrappers, and any future thin adapter.

Codex-specific sidecar metadata (`agents/openai.yaml`) is intentionally absent from the Yoke skill tree by default. If Yoke eventually needs hard Codex-only invocation policy or UI metadata, generate those sidecars from a single canonical manifest instead of hand-authoring one file per skill.
