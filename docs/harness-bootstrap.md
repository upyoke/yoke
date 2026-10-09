# Harness Bootstrap Contract (internal)

*Yoke-owned neutral bootstrap contract for any harness. This document defines what every harness must do at session startup and how Yoke surfaces are classified for harness-facing use.*

## 1. Startup Reads

Every harness must load the startup reads defined in the neutral bootstrap spec at `runtime/harness/bootstrap-spec.json`, regardless of whether the harness uses hooks to inject them or loads them via an explicit wrapper command. Startup orientation omits the optional recent commit, then the branch name, when long Git metadata would exceed the smallest harness inline UTF-8 budget; identity, advisories, and authority/trust instructions remain intact.

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

The shared bootstrap render path (`yoke_core.hooks.bootstrap.render_compact` and `render_full`) injects the layer-explicit `main_agent` packet block via [`yoke_core.domain.main_agent_packet`](../packages/yoke-core/src/yoke_core/domain/main_agent_packet.py). The block is generated, never hand-copied: the body comes from `yoke_core.domain.schema_api_context.render_role_packet("main_agent")` and stays in lockstep with subagent packets via the schema/API-context drift check.

The injection means the top-level Yoke session sees the same compact `core` + `claims` spine the read-only subagents (`architect_agent`, `simulator_agent`, `boss_agent`) see, alongside the file-reads list and Critical Runtime Invariants block. Harnesses that consume the shared bootstrap render path (via `yoke_core.hooks` for both Codex and Claude Code) inherit the packet automatically.

If the schema/API context generator is unavailable (fresh checkout, broken bootstrap state), the bootstrap path stays fail-open: the helper returns an empty block and the orientation continues with file-reads + invariants only. There is no path that hand-copies stale packet content into the orientation prose.

## 1a. Layer Names: `main_agent` vs. `harness_contract`

Yoke packet vocabulary is layer-explicit and does not mix LLM-facing schema/API context with the substrate manifest contract. Two layer names matter for harness adapters and operator docs:

- **LLM-facing packet layer** — `main_agent`, `architect_agent`, `engineer_agent`, `tester_agent`, `simulator_agent`, `boss_agent`, `qa_walker_agent`. These are the role keys in `yoke_core.domain.schema_api_context_seed.ROLE_TOPICS`. The renderer expands marker pairs in canonical agent prompts (`runtime/agents/<role>.md`) using these names; the bootstrap path injects the `main_agent` block via `yoke_core.domain.main_agent_packet`.
- **Substrate contract layer** — `harness_contract`. This name covers manifest- and bootstrap-derived substrate capability truth: hooks, env / session identity, cwd binding, adapter render format, supported commands, disabled paths, wake primitives (`agent_wake`), known parity limits. The manifest is the authority for every one of those facts: no doc, skill, rules file, or agent body states one on its own, and a surface that shows a capability to a reader renders it from the manifest instead. It lives in this file (`docs/harness-bootstrap.md`) and in the per-harness manifest schema documented at [`runtime/harness/manifest-schema.md`](../runtime/harness/manifest-schema.md). `harness_contract` is deliberately NOT a `schema_api_context` role; the renderer does not produce a packet body for it.

The two layers are kept separate so an LLM packet referring to `harness_contract` content (or vice versa) is structurally invalid. Adding a new harness adapter means writing or updating the harness's `manifest.json` and `manifest-schema.md` entry under `harness_contract`, not adding a new `schema_api_context` role.

## 2. Safe Operator Commands

These are the top-level `/yoke` commands that constitute the safe operator interface. Any harness may invoke these commands. They are the only sanctioned entry points for external harness interaction with Yoke.

<!-- BEGIN GENERATED: skill-registry -->
Skill metadata is generated from `yoke_contracts.skill_registry`.
Change that source and run `yoke dev run -- python3 -m
yoke_core.tools.render_skill_registry_inline --target-root CHECKOUT`.

| Skill | Kind | Session mode | Autonomy | Purpose |
|---|---|---|---|---|
| `/yoke blitz {PREFIX-N}` | stage | `blitz` | autonomous execution | execute document-led work |
| `/yoke charge [--dry-run] [--item PREFIX-N] [--project P] [--wip-cap N]` | orchestrator | `charge` | autonomous execution | select runnable frontier work |
| `/yoke conduct PREFIX-N [--max-attempts N] [--no-chain]` | stage | `conduct` | autonomous execution | execute generated task lanes |
| `/yoke curate (no arguments)` | utility | `curate` | follow skill decision gates | curate the Ouroboros learning log |
| `/yoke dash "instruction" \| {PREFIX-N}` | stage | `dash` | autonomous execution | execute instruction-led work |
| `/yoke doctor [project] [--fix] [--file path]` | utility | `doctor` | follow skill decision gates | run health checks |
| `/yoke feed [--no-new-items] [PREFIX-N ...] [--model MODEL]` | orchestrator | `feed` | follow skill decision gates | refresh frontier work |
| `/yoke help` | utility | `wait` | follow skill decision gates | show command reference |
| `/yoke idea [--dry-run] [--workflow issue\|epic\|blitz\|task] {title}` | utility | `idea` | follow skill decision gates | file a backlog item |
| `/yoke implement {PREFIX-N} [--no-worktree] [--force] [--qa-bypass]` | stage | `implement` | autonomous execution | implement and review an item |
| `/yoke models lookup MODEL_ID \| get \| validate \| diff \| publish \| revisions \| restore \| level-proposal` | utility | `wait` | follow skill decision gates | publish model catalog revisions and propose level changes |
| `/yoke onboard [--project P] [--run-id RUN]` | orchestrator | `wait` | follow skill decision gates | make a wired project execution-ready |
| `/yoke polish {PREFIX-N}` | stage | `polish` | autonomous execution | review and finish implementation |
| `/yoke refine {PREFIX-N}` | stage | `refine` | follow skill decision gates | critique and improve item artifacts |
| `/yoke resync [--fix]` | utility | `wait` | follow skill decision gates | detect and repair GitHub drift |
| `/yoke shepherd {PREFIX-N}` | stage | `shepherd` | autonomous execution | execute the pinned planning interval |
| `/yoke simulate {epic-ref} [--auto-fix] \| --system` | utility | `simulate` | follow skill decision gates | trace integration paths; no terminal `yoke simulate` adapter |
| `/yoke steer [STRATEGY-DOC-SLUG] [--project P ...]` | orchestrator | `steer` | autonomous execution | staff work from a strategy document; omitted slug defaults to `CURRENT-PLAN` |
| `/yoke strategize [--model MODEL]` | orchestrator | `strategize` | follow skill decision gates | review project strategy |
| `/yoke usher PREFIX-N [PREFIX-N ...] [--dry-run] [--merge-only] [--deploy-only] [--resume PREFIX-N]` | stage | `usher` | autonomous execution | merge and deliver an item |
| `/yoke wrapup (no arguments)` | utility | `wrapup` | follow skill decision gates | wrap up the session |
<!-- END GENERATED: skill-registry -->

## 3. Command Classification

Yoke surfaces are classified into three tiers. The tier determines whether a harness should invoke a surface directly.

### Tier 1: Top-level operator commands

These are the commands listed in section 2 above. They are the sanctioned external interface. Every harness should use only these commands for Yoke interaction.

The generated registry above owns membership. Read each skill for its decision gates.

### Tier 2: Internal sub-skills

These are called by operator commands or other sub-skills. They have SKILL.md files and can technically be invoked directly, but they are not part of the primary operator interface. A harness should not invoke these directly unless it is implementing a specific downstream path that Yoke core has routed to it.

Stage skills write status through `lifecycle.transition.execute` (`yoke lifecycle transition PREFIX-N --to <next-stage>`), which enforces the pinned workflow gates. Commit fixes and refresh affected QA evidence before transitioning.

<!-- BEGIN GENERATED: skill-registry-internal -->
Internal skills are generated from `yoke_contracts.skill_registry`.

| Skill body | Purpose |
|---|---|
| `.agents/skills/yoke/amend/SKILL.md` | amend a synced task graph |
| `.agents/skills/yoke/approve/SKILL.md` | record a deployment approval |
| `.agents/skills/yoke/implement/implementing/SKILL.md` | kick off implementation |
<!-- END GENERATED: skill-registry-internal -->

### Tier 3: Raw internal Python entrypoints

These are internal implementation mechanisms. A harness must never invoke these directly. They are the plumbing beneath the operator commands and sub-skills.

**Examples of raw Python entrypoints (never invoke directly from a harness):**

- Direct item creation through the db-router internals -- use `/yoke idea` instead.
- Direct item updates through the db-router internals -- use the `items.structured_field.replace` / `items.scalar.update` function ids (see [`.yoke/docs/reference/db-reference/functions.md`](../.yoke/docs/reference/db-reference/functions.md)) or the wrapped operator surface where one exists.
- `python3 -m yoke_core.cli.db_router query` -- source-dev/operator-debug raw SQL break-glass; everyday diagnostics use `yoke db read`
- Direct epic db-router operations -- operator/debug adapters for the `workflow_item.epic_task.*` and `workflow_item.epic_progress_note.append` function family.
- `yoke_core.domain.emit_event` -- internal event emitter module.
- `yoke board rebuild` -- operator/debug adapter that dispatches `board.rebuild.run`
- `yoke_core.engines.repair_status` / `yoke_core.domain.update_status` -- internal lifecycle transition modules (agent path: `lifecycle.transition`).
- Direct `yoke_core.api.service_client` session and claim adapters -- operator/debug fallbacks for session lifecycle, `db_claim.amend`, and claim families. Prefer wrapped `yoke claims work ...` and `yoke claims path ...` surfaces where they exist.
- `yoke_core.domain.worktree` -- internal worktree creation, resolution, and install module.
- `yoke_core.domain.item_field_transform` -- internal structured-field transform adapter for `items.structured_field.append_addendum` / `section_upsert` / `section_append`.
- Direct epic task body updates through `yoke_core.domain.epic` -- operator/debug adapter for `workflow_item.epic_task.body_replace`.

The Python entrypoints above are internal surfaces. Agents use registered `yoke` commands; external tools such as Git and package managers retain their native commands.

**Why this matters:** Raw internal entrypoints assume Yoke's invariants (DB state, lifecycle ordering, hook enforcement, event emission). Calling them directly from a harness bypasses the safety gates, lifecycle validation, and audit trail that operator commands provide. The result is corrupted state, missing events, and broken invariants.

## 4. Session Identity Expectations

When a harness connects to Yoke, Yoke records session identity during registration so staffing and lifecycle operations use the same identity.

### Required identity fields

| Field | Description | Source |
|-------|-------------|--------|
| `executor` | The harness identity declared at registration (`sessions begin`) time. Surface-specific values such as `claude-desktop`, `codex-vscode`, or `codex-cli` are accepted as input; Yoke canonicalizes the value at write time so `harness_sessions.executor` stores only `claude-code` or `codex`, and the original surface alias is preserved in `harness_sessions.executor_surface` for operator-facing rendering. A session whose surface was not resolvable when it registered is not stuck NULL: the hook tail observes the existing row on every later event, terminal ones included, and fills the surface once the harness names it — on the machine actually running the session. A relayed evaluation records only the surface the client sent, because the surface a server can see is its own. Level labeling matches the harness family, so any surface of a harness matches that harness's level options. | Harness self-declaration |
| `provider` | The model provider (e.g., `anthropic`, `openai`) | Runtime or harness configuration |
| `model` | The specific model identifier (e.g., `claude-opus-4-7`, `o3-pro`) | Runtime or harness configuration |
| `workspace` | The git repository root path | `git rev-parse --show-toplevel` |
| `session_id` | A unique session identifier | Harness-generated canonical id. Supported harnesses (`claude-code`, `codex`) MUST pass their canonical session id; auto-generated fallbacks are rejected at the service boundary. |

### Optional identity fields

| Field | Description | Source |
|-------|-------------|--------|
| `supported_paths` | Which downstream Yoke paths this harness can execute | Yoke core derives this server-side from the shared registry plus any limitations in the coarse harness manifest. Surface-specific executors normalize back to the family manifest (`codex-desktop` -> `runtime/harness/codex/manifest.json`, `claude-vscode` -> `runtime/harness/claude/manifest.json`). Harness-passed values are ignored for Yoke-owned harnesses. Harnesses without a manifest fall into the backward-compat branch (empty list = all paths supported). |
| `hook_affordances` | Which hook events the harness supports | Harness capability manifest |
| `agent_wake` | Whether an ended turn can be resumed out of band, and by which primitive | Harness capability manifest, sourced from `yoke_contracts.harness_wake_capability` |
| `execution_level` | Execution level identity (e.g., `DARIUS`) | Harness or operator configuration |

### Requested launch selection versus served identity

A managed launch persists typed model, reasoning-effort, and context-window requests separately from provider-attested served identity; registration stamps missing requested values, while UI and fleet views label requests and show both values when they differ.

Adapter encoding is manifest-declared: Claude uses `--model`, `--effort`, and a `[1m]` model selector; Codex uses `--model` and `-c model_reasoning_effort=...` without context selection. Cursor passes the advertised native model selector unchanged. Preview resolves effort to an observed variant, rejects conflicting effort, and accepts an explicit context window only when that exact variant's native label names it. Native labels describe selectable options; they never attest a running session's context window.

Preview validates every knob and reports a harness-specific refusal. Cursor discovers models through `cursor-agent --list-models`; Claude and Codex expose documented identifiers. Runtime rejections become `model_combo_unsupported` with bounded safe detail and never trigger silent fallback.

### Identity resolution

Yoke does not prescribe how a harness resolves these fields. The harness may:

- Read them from its own runtime environment
- Declare them in a static capability manifest
- Derive them from configuration files
- Report them dynamically at registration

The only requirement is that the values are truthful. Yoke uses these fields to decide what work to route and what to fall back on. False identity leads to failed routing.

### Session scratch cleanup

The machine-throttled stale-session scratch janitor removes only known artifacts with positively dead owners: ended registered sessions or non-harness `session-unknown` runs whose `pid-N` process is no longer alive. All active, unknown, live, or unverifiable owners are preserved; PID liveness is rechecked before deletion and a machine lock prevents concurrent sweepers.

`/yoke doctor --fix` uses the same proof rules. If the registry is unavailable, mutation fails closed and the doctor never treats filesystem age alone as ownership proof.

For supported harnesses such as Claude Code and Codex, `session_id` should come from the harness runtime's stable conversation identifier (`CLAUDE_CODE_SESSION_ID`, `CODEX_SESSION_ID`, or a hook payload `session_id` when the env var is unavailable). Do not invent a second ID format for those harnesses. Codex also exports `CODEX_THREAD_ID`, which names the thread actually running and is the *child* inside a subagent; the canonical chain consults it only after `CODEX_SESSION_ID`. Every one of these variables is inherited by whatever the harness starts, so the chain reads only the variables of the family the process tree names — a harness launched from inside another harness's shell resolves to itself or to nothing, never to its launcher.

### Path support and fallback

For supported harnesses, Yoke core derives the effective `supported_paths` server-side from the shared registry plus any limitations in the coarse harness manifest. Surface-specific executor values normalize back to their family manifest (`codex-desktop` -> `runtime/harness/codex/manifest.json`, `claude-vscode` -> `runtime/harness/claude/manifest.json`). Both `codex` and `claude-code` ship a manifest in the shared schema documented at [`runtime/harness/manifest-schema.md`](../runtime/harness/manifest-schema.md). Harnesses without a manifest fall into the backward-compat branch (empty list = all paths supported). Work requiring an unsupported downstream path falls back gracefully -- Yoke does not route unsupported work.

Supported paths are resolved from the harness manifest. When no manifest exists for the executor, the session is treated as unconstrained for downstream-path validation. Adapters that want truthful fallback enforcement should add a manifest under `runtime/harness/{executor}/manifest.json` (or normalize their own surface-specific executors back to a family manifest the way Yoke-owned harnesses do); harness-passed `supported_paths` is ignored for Yoke-owned harnesses. Yoke-owned manifests should declare limitations, not copied command/path allowlists.

## 4b. Machine identity and launcher authority

The machine itself is registered before any of this matters: `yoke setup` registers this host's machine id at the end of Apply and `yoke status` registers it whenever it runs, giving it an owner and a human name, and the `machines` row's `access` document decides which same-universe actors may spend that machine's launch capacity — an unregistered machine is never launchable, and the refusal names the recovery, `yoke machine register`. `HC-machine-registry` checks the local id against the row; the full contract is [`machine-registry.md`](machine-registry.md).

The launcher-authority doctor probe uses the user's `$SHELL`, or `/bin/sh` when unset. The unmatched-glob guard blocks only for zsh: an explicit command shell takes precedence over the harness's inherited `$SHELL`; an unknown shell allows the glob. Both local and relayed glob guards use the same resolver. The path-authority guard and scratch writers also admit the canonical `$TMPDIR` when it is set to an absolute path. The login-shell `yoke` on PATH must be the canonical shim (`$XDG_BIN_HOME/yoke` or `~/.local/bin/yoke`) pointing at the registered checkout editable install. `python3 -m yoke_core.tools.install_yoke_launcher` writes it. `--repair` and `yoke doctor run --quick --fix` (HC-launcher-authority) quarantine PATH shadows and never delete them.

### Standing relay release authority

`yoke setup` installs the relay of the connection it is writing, naming that environment and machine config to the packaged installer rather than letting the child resolve whatever this host happens to point at. The step is convergent, so the on-screen retry after a failed Apply is safe: setup first asks the installer whether this exact relay is already satisfied — loaded, carrying the native service document this configuration would write now, and pointed at a present, current build — and leaves a satisfied relay running untouched. Anything short of satisfied, including an unreadable status, is a real upgrade or repair and installs normally. A failed install carries the installer's own refusal code, exit status, and recovery, credential-redacted and bounded, because the installer's diagnosis is the only record of why an install that succeeds standalone did not succeed here.

On macOS the LaunchAgent, and on Linux the systemd user service, executes `<relay instance state>/venv/bin/yoke`; that stable link always targets the fixed `runtime` directory and its copied relay-owned Python. Python starts in isolated mode, then the bootstrap resolves the active `release` pointer once and exports only that physical release's package path for itself and supervised Python children, naming its own state directory alongside it so that export can be undone precisely. When a relay process starts an actual vendor CLI — the Claude or Cursor native under the supervisor, `codex exec`, the codex app-server, or any installed-surface probe — that child starts with the activation variables dropped and the relay's own `bin` directories filtered out of its search path, so a project command inside a launched session installs into the project it is working in and never into the relay. The user's own path entries, including the machine's installed `yoke` launcher, are untouched. Stripping any earlier would break the relay's own Python children, which reach the running release through exactly those variables. The selected release environment contains the exact immutable `yoke-core` build served by the environment and obtained from its distribution index; it never executes a checkout. This does not add an onboarding permission step or require Developer Tools Access: macOS consent remains conditional on a launched tool actually reaching protected or iCloud-backed content.

A relay bound to a local universe has no served release to follow, because the machine running the relay is also the machine serving the control plane. Its native user service executes this machine's installed launcher (`$XDG_BIN_HOME/yoke` or `~/.local/bin/yoke`) directly, so the relay runs whatever Yoke the operator installed and upgrades with it; there is no pinned release, no distribution index, and no handshake to compare against. `yoke relay install` converges that relay by confirming the launcher is present, refusing with `relay_local_launcher_missing` and the `install_yoke_launcher` recovery when it is not, and `yoke relay status` reports the launcher it runs instead of a pin. A prod-flagged local-postgres connection owns no relay at all: it is direct database authority for a universe an https connection already serves, and that connection's relay is the one to use.
On Linux, onboarding enables the environment's `com.upyoke.relay[.<environment-id>].service` under `~/.config/systemd/user/`. It starts at login, restarts on failure, and stops after the last login session logs out. No linger is enabled; an already lingering user is refused with a disable-linger recovery. `yoke relay install|status|uninstall` owns the same lifecycle as the macOS LaunchAgent. Doctor checks an active, enabled, current unit, authenticated heartbeat, and logout behavior. A host without systemd as PID 1 or without a user manager reports that the relay is not supervised and how to recover. See [Linux relay supervision](public/reference/linux-relay.md).

Each successful poll handshake compares the freshly served build with the installed receipt. A change installs beside the active release, atomically repoints the `release` link, drains in-flight jobs, and execs the unchanged runtime entrypoint. A full user-service restart begins through that same physical relay-owned interpreter, while every release keeps its own package directory. Only a fresh handshake can trigger a repin; there is no timer or cron. A fetch failure is `relay_release_fetch_failed`, preserves the working process, runtime identity, and pin, and records the retry command. `yoke relay status` shows pinned and served builds, the current control-plane poll outcome (a loaded agent is not a working connection), and that recovery evidence.

A matching receipt is not proof that the release runs. Readiness loads the pinned release the way the launcher loads it -- the stable runtime interpreter in isolated mode, that release's own packages first on `sys.path`, `yoke_cli.main` imported, and `yoke-core` reporting the pinned version from inside that release -- so a release whose packages an editable install replaced with pointers, or whose package is resolved from a checkout outside the release, reports `package_ready=false` with `relay_release_install_failed` and the import failure that named it. The reuse decision reads the same answer, so `yoke relay install` rebuilds a broken release that still matches the served build instead of restarting into it, and it loads each candidate the same way before the pointer swap; a candidate that fails to load leaves the prior release pinned and running. The load is bounded by a timeout it names rather than hanging the status call, and it happens only where readiness or reuse is asserted -- never on the poll heartbeat.

A terminal relay report is permanently rejected when the server will never accept it: `report_conflict` (already settled), `relay_lease_expired` (its batch expired before the report), `invalid_state` (the job already closed), `attempt_missing` or `lease_mismatch` (never leased to this relay), or an invalid payload. Launch reports enter local quarantine after three permanent rejections, and those retries never hold the relay's claims. Wake reports enter quarantine immediately; permanently rejected evidence is logged and dropped. Finished resume custody is released just as on success, while the quarantined error code remains visible in relay health; do not replay it. Connectivity and ambiguous failures retain resume custody for the next poll, or the durable retry queue for launches, and a launch report awaiting such a retry holds new claims until it drains. An operator may preserve one already diagnosed permanent rejection early with `yoke relay report quarantine <opaque-report-id>`; the command refuses reports without report-scoped permanent-rejection evidence and records the preserved path and SHA-256.

Claude usage counts each assistant message id once across rows and incremental folds, including history repeated after compaction. Its watermark stores distinct ids and per-model totals without transcript content; ids, totals, reader version and offset save atomically. Codex readings replace cumulative totals rather than adding them.

Every child interpreter used by release installation runs in isolated mode so the relay's inherited package path cannot select the running release during candidate installation or verification. Repair a mismatched relay pin from an ordinary login shell with `yoke --env ENV relay install`; if that shell exports `PYTHONPATH`, remove it for this invocation. The updater preserves installed releases and the last working pin, restarts the native user service, and resumes relayed sessions on the next poll.

Hook and guard verdicts print `{source_sha, install_kind, install_path}` so version skew is a fingerprint, not a reconstruction. Relayed verdicts echo client and server fingerprints; a relay timeout prints `fallback=local`. The server binds the authorized request's project to scratch resolution for the entire hook run, including lifecycle dedup, Codex cache and prompt markers, orientation markers, and item-marker writers. This request-local binding reaches typed workers without changing process-wide environment or guessing from the server checkout. Local path evaluation refuses to POST a payload whose stamped `session_id` is missing or still conversation-shaped unless the client set `identity_stamped`. Identity-resolution failures deny writes only. `YOKE_HOOK_REPLAY=1 yoke hook evaluate <event>` returns the same verdict without writing process-anchors, the cursor-session-map, remount-expect receipts, or registering a session.

A Cursor remount mints a new conversation id and does not name the prior session. While the holder is still on the main checkout, each client hook refreshes a short-lived remount-expect receipt under `cursor-session-map/remount-expect/`. The first hook in the linked worktree consumes that receipt before aliasing the new conversation onto the holder. A worktree workspace with a live claim holder and no receipt is identity-failure, not a folder fold.

## 4c. Unattended permission posture

Every harness decides from its own persisted machine config whether to stop
and ask before running a command, and every one ships defaults that ask.
Yoke's launched workers never see those prompts — the launch plane passes
each harness a bypass flag, declared once in
`yoke_contracts.session_control.launch_permission_bypass`. A session a
*person* opens reads the persisted config instead, so a fresh install has
someone approving each `yoke` call by hand, including the field-note command
Yoke tells them to run when something goes wrong.

`python3 -m yoke_core.tools.install_yoke_launcher` therefore writes the same
posture into each installed harness, on both first install and `--repair`.
The keys live in `yoke_contracts.harness_unattended_posture`:

| Harness | Config | Keys |
|---|---|---|
| `claude-code` | Platform `claude_desktop_config.json` ([Linux paths](harness-linux.md)) + `~/.claude/settings.json` | `preferences.bypassPermissionsModeEnabled`, `permissions.defaultMode` |
| `codex` | `$CODEX_HOME/config.toml` | `approval_policy`, `sandbox_mode` |
| `cursor` | `~/.cursor/cli-config.json` | `approvalMode`, `sandbox.mode` |

`yoke setup` plans it as a named step, **Unattended harness posture** —
previewed in Review, naming each harness, file, key, and the undo.
`--skip-harness-permissions` excludes it from interactive and noninteractive preview/apply.

Approval posture is machine-wide; **folder trust is per path**, and a machine
with one still stops on the other — a Codex session with `approval_policy =
"never"` still asks about the directory first. Yoke answers that too, at
project install for the checkout and at lane creation for each worktree:

| Harness | Where trust is recorded |
|---|---|
| `claude-code` | `~/.claude.json` → `projects.<path>.hasTrustDialogAccepted` |
| `codex` | `$CODEX_HOME/config.toml` → `[projects."<path>"] trust_level` |
| `cursor` | `~/.cursor/projects/<slug>/.workspace-trusted` |

Trust is path-keyed in all three with no evidence any treats a parent's entry
as covering a subdirectory — the shape Codex hook trust already has — so a
linked worktree gets its own entry rather than inheriting the checkout's.

One thing defeats all of this and no config can fix it: **wrapping `yoke` in
a shell loop or command substitution.** Allowing commands that start with
`yoke` matches a first word, so `for slug in A B C; do yoke ...; done`
presents `for` and prompts again. Recipes spell repeated calls out plainly.

All three are machine-level because that is where each harness reads them:
Codex reads no project-local config at all.

Three properties hold for every pass, because widening what a harness runs
without asking is the operator's business:

* **A key you set yourself is never overwritten.** Only an absent key is
  written; a differing value is reported, not changed.
* **Every unrelated setting survives.** These files hold model choices, hook
  trust, and auth cache, so each pass edits in place rather than rewriting.
* **It says what it did.** Each write is named in the output,
  `collect_harness_inventory` reports each harness's `unattended_posture`,
  and `HC-harness-unattended-posture` fails with the offending key and the
  repair when any installed harness still prompts.

A harness that is not installed on the machine is skipped, not created.

## 5. Repo-local Skill Discovery

Yoke skills live canonically in the **hidden** repo-local directory `.agents/skills/yoke/`. Modern Codex runtimes natively scan repo-local `.agents/skills` locations, so the Yoke skill tree is a first-class Codex skill source when Codex starts in this repository. No `.codex/skills` mirror is required.

Because the directory is hidden, generic discovery (e.g. `rg --files`, plain `ls`) still skips it unless the caller explicitly includes hidden paths. Wrapper-only harnesses, thin docs, and operator tooling therefore cannot guess the canonical location -- they must consume a Yoke-owned resolver.

### Canonical layout

- `.agents/skills/yoke/SKILL.md` — the root `/yoke` router skill.
- `.agents/skills/yoke/{name}/SKILL.md` — each direct subskill (`idea`, `shepherd`, `strategize`, etc.).
- `.agents/skills/yoke/{name}/*.md` — **phase sub-files** (e.g. `implement/entry.md`). These are *not* standalone skills and are never returned by the discovery surface.
- `.agents/skills/yoke/{name}/{nested}/SKILL.md` — nested internal skills may be visible to Codex's native scanner even when Yoke's resolver hides them. They still use their own `SKILL.md` frontmatter as the shared metadata source.
- `.agents/skills/yoke/{scripts,shared}/` — supporting directories without a top-level `SKILL.md`. Discovery ignores them.

`.claude/skills/yoke` is a **native discovery symlink** that points at `../../.agents/skills/yoke`. Claude Code's built-in skill loader follows it, but wrappers, thin docs, and operator tooling must treat `.claude/skills/yoke/...` as discovery-only — the canonical form is always the `.agents/...` path.

### Discovery surface

The `yoke_core.hooks.bootstrap` module owns repo-local skill discovery: `skill-list` enumerates skills and `skill-path` resolves a name to its canonical `SKILL.md` path.
No wrapped product CLI exists for this harness bootstrap resolver yet.

- `skill-list` enumerates top-level Yoke skill names from `.agents/skills/yoke/`. The first entry is always the root router skill (`yoke`). Each subsequent entry is a direct subdirectory that contains a `SKILL.md`. Phase sub-files and directories without a top-level `SKILL.md` are excluded.
- `skill-path <name>` returns the absolute canonical `.agents/...` `SKILL.md` path. For the root router skill, `skill-path yoke` returns `.agents/skills/yoke/SKILL.md`.
- Missing skills exit non-zero with a clear `not found at <canonical path>` message on stderr. The resolver never falls back to `~/.agents`, `~/.codex/skills`, or any home-directory guess — if the repo-local path is missing, the resolver fails loudly rather than silently resolving to a platform global.
- `--root` defaults to the current working directory when omitted. `--spec` is *not* required for the discovery modes; they operate purely against `.agents/skills/yoke/`.

### When to consume the resolver

| Caller | What to do |
|--------|-----------|
| Codex native skill loader | Let Codex scan `.agents/skills` directly; use `SKILL.md` frontmatter as the shared metadata source. |
| Wrapper-only harness bootstrap (no hooks available) | Invoke the resolver to confirm the canonical tree exists before delegating to `/yoke` commands. |
| Thin docs that list available skills | Derive the list from `skill-list` instead of hardcoding, so the doc never drifts from the repo. |
| Operator shell commands composing a skill path | Call `skill-path` rather than concatenating `.agents/skills/yoke/<name>/SKILL.md` by hand. |
| Claude Code's native Skill tool | Continue to use the harness-owned loader; this contract is for repo-local wrapper discovery, not Claude Code's built-in skill surface. |

Harnesses that need a shell-native resolver should only introduce one when an actual current shell wrapper requires it. Symmetry with existing shell inventories is not enough justification -- the Python surface above is harness-neutral and works for Codex, Claude Code wrappers, and any future thin adapter.

Codex-specific sidecar metadata (`agents/openai.yaml`) is intentionally absent from the Yoke skill tree by default. If Yoke eventually needs hard Codex-only invocation policy or UI metadata, generate those sidecars from a single canonical manifest instead of hand-authoring one file per skill.

## 6. Hook Approval

Installing hook glue does not make it run. A harness with a readable approval gate fails **silently** when approval is missing: the session looks ordinary while no telemetry is written.

Each harness's gate is declared once, in `yoke_contracts.harness_hook_approval`. A harness absent from that mapping has no declared hook-specific approval requirement, not proof there is no trust gate. Claude Code is absent because folder-trust does not gate hooks. Cursor is absent because [official hooks documentation](https://cursor.com/docs/hooks) auto-load project `.cursor/hooks.json` in a trusted workspace and do not document a hook-approval or reapproval prompt. Workspace trust is a separate, default-off security gate. Two surfaces read the declaration rather than branching on a harness id:

| Reader | What it does with the declaration |
|--------|-----------------------------------|
| `yoke project install` / `yoke setup` | Mints exact trust for the Yoke-authored Codex hooks file; records an approval sentence for each remaining operator-owned gate under `harness_hook_trust`. |
| The Overview's harness activation module | Reports per-target hook health (green / orange / red). Orange means installed without recent telemetry; red names the approval surface when approval state is readable and untrusted. |

Two properties of the gate matter more than the mechanics:

- **Approval is per literal checkout path.** Install mints the main checkout's exact current Codex hashes; worktree preparation mirrors them only onto a byte-identical lane.
- **Approval follows content.** Install replaces the main checkout's stale hashes after writing Yoke-owned glue. A change outside that boundary still invalidates the hash and legitimately returns activation to red until the operator re-trusts it.

Yoke grants only the Codex hashes for the hooks file it just authored. Other harness gates and non-Yoke hook changes remain operator-owned. Doctor tells the truth afterward about the main checkout, lanes, and stale deleted-path entries.
