# Codex harness operations

This file is the Codex-facing entry point for Yoke. It references the shared bootstrap contract and lists the narrow safe command surface for Codex sessions.

Shared project rules load from the canonical `AGENTS.md`. This guide explains Codex-specific operations; it is an ordinary reference, not an additional auto-loaded instruction file.

Each standing rule in `AGENTS.md` names a deep home under `.yoke/docs/reference/agent-rules/` carrying the reasoning, recovery paths, and worked failure modes behind it; `AGENTS.md` lists which file covers which operation. Read the one that governs an operation before performing it, and read an operation's own `--help` for its variants and flags.

The `## Simplify — three-axis doctrine` section in `AGENTS.md` defines the shared **reuse / quality / efficiency** vocabulary, future-concept pull-forward lens, and stage weights used by every authoring step (idea, refine, implement, shepherd, conduct, polish). Codex sessions read it from `AGENTS.md`; this file does not duplicate it. The doctrine is Yoke-owned and harness-neutral — do not treat any Claude-only built-in as a dependency.

## Bootstrap

Codex loads its Yoke orientation automatically from the canonical auto-loaded `AGENTS.md` plus the session-start hook, which injects the same orientation and the generated `main_agent` packet block other supported harness sessions receive. That gives Codex's main session the same compact `core` + `claims` schema/API spine the Bash-capable subagents see. Substrate capability truth (hooks, env / session identity, cwd binding, adapter render format, supported commands, parity limits) is documented separately as the `harness_contract` manifest, which the Codex adapter carries alongside this shell. `harness_contract` is the manifest layer; `main_agent` and `*_agent` are the LLM-facing packet layer — the two never overlap.

### Repo-local skill discovery

Yoke skills live canonically in the hidden directory `.agents/skills/yoke/`. Codex treats that repo-local `.agents/skills` tree as a native skill source, so no `.codex/skills` mirror or plugin install is required for ordinary Yoke work. Codex progressive disclosure loads each skill's frontmatter first and reads the full `SKILL.md` only when the skill is invoked. Claude requires `.claude/skills/yoke`, a native discovery symlink to the canonical tree in both source and installed projects. Codex and Cursor discover `.agents/skills` directly. No regular discovery copies are installed; native symlink support is required. See [native discovery](../reference/harness-discovery.md).

## Approval and sandbox posture

Codex decides whether to stop and ask before running a command from
`$CODEX_HOME/config.toml`, and it reads no project-local config, so that
machine file is the only place the answer can live. Its defaults ask — and
its default sandbox denies every outbound socket, which is what a local
Postgres control plane listens on, so an unconfigured machine cannot reach
Yoke at all and cannot run the field-note command it is told to fall back to.

The launcher install (`python3 -m yoke_core.tools.install_yoke_launcher`,
first run and `--repair`) writes what Codex needs into that file:
`approval_policy` and `sandbox_mode` from the same declaration the launch
plane already passes launched workers, plus a `[projects."<checkout>"]` trust
entry so Codex does not ask about the directory either. It only writes a key
that is absent, reports rather than overwrites a value you set yourself, and
leaves your model choices and hook trust untouched.

If a `yoke` command is refused with `Operation not permitted`, that is this
posture missing, not a broken database: the CLI says so and names the repair.
`HC-harness-unattended-posture` reports the standing posture for every
harness on the machine.

**Never wrap `yoke` in a shell loop or command substitution.** An operator
who allows commands starting with `yoke` is allowing a first word, so
`for slug in A B C; do yoke ...; done` presents `for` and asks again — every
call inside it was already permitted, and the composition is what re-prompts.
Run repeated calls as separate plain invocations.

## Work-item entry surfaces

Every create selects a workflow and a typed entry surface (`web_form`, `cli`, `harness_skill`, or `promotion`); the pinned immutable workflow version must allow that surface. `/yoke idea` drives the registered `items.create` function through `harness_skill`, while product forms and operator commands use their own typed surfaces. Dry-run and test-isolated DB targets may omit the surface.

## Safe Command Surface

Codex sessions use the shared Yoke operator surface unless the Codex manifest declares a concrete substrate limitation.

### Supported entrypoints

| Command | Description |
|---------|-------------|
| `/yoke idea "title"` | File a new backlog item |
| `/yoke refine PREFIX-N` | Critique and improve item artifacts (no worktree, no code) |
| `/yoke implement PREFIX-N` | Drive a pinned `implement` segment in its registered single worktree lane |
| `/yoke conduct PREFIX-N` | Drive a pinned generated-task segment via shared dispatch descriptors |
| `/yoke polish PREFIX-N` | Review and finish implementation in existing worktree |
| `/yoke usher PREFIX-N [--dry-run]` | Merge/deploy handoff for implemented items; use dry-run first for Codex validation |

### Supported downstream paths

Codex supports these downstream paths (derived server-side from the shared Yoke registry, then limited by the Codex manifest only when the manifest declares an explicit limitation):

| Path | Description |
|------|-------------|
| `shepherd` | Drive an item through quality-gated lifecycle to ready |
| `refine` | Critique and improve item artifacts |
| `implement` | Definition-bound single-lane implementation through review |
| `dash` | Direct execution from one instruction, any size: survey, worktree, verify, merge, evidence |
| `blitz` | Document-led direct execution from the item's single linked strategy document |
| `conduct` | Definition-bound task-graph loop that dispatches Engineer / Tester / Architect / Simulator |
| `polish` | Review and finish implementation in existing worktree |
| `usher` | Merge and deploy implemented/release items through the top-level operator flow |

Work requiring paths outside this shared delivery-path set still falls back with a clear message. Yoke core derives the path list from the shared registry plus manifest-declared limitations — the harness no longer self-reports capabilities via environment variables.

### Limitations

The Codex manifest is the source of truth for substrate limitations and currently declares none on entrypoints or downstream paths. The full operator surface — including `/yoke conduct`, `/yoke resync`, `/yoke curate`, `/yoke wrapup`, `/yoke feed`, `/yoke strategize`, and `/yoke charge` — is part of Codex's safe surface. Conduct dispatches the same `yoke-engineer`, `yoke-tester`, `yoke-architect`, and `yoke-simulator` agent bodies as Claude, rendered into Codex custom agents from the canonical agent bodies. The shared dispatch descriptor emits the same task envelope for both harnesses, so phase files name agents through descriptors rather than a Claude-only `subagent_type`. Result ingestion is parseable on both sides, and tool-call telemetry flows into the same event stream.

The remaining named substrate gap is on the telemetry edge: Codex does not emit a dedicated `PostToolUseFailure` event for non-Bash tools (Write/Edit/Read). Bash failures on Codex are recovered inside the `PostToolUse` handler via exit-code parsing, hard-failure text matching, and last-resort transcript reconciliation against `tool_use_id` ↔ rollout `call_id`.

Future shared-registry additions inherit to Codex unless a real substrate limitation is declared in the manifest.

## Shell differences on Codex

`AGENTS.md` and the Yoke skills write their search recipes around `rg`, which
Claude Code ships as a shell builtin. Codex has no such builtin, so unless
ripgrep is separately installed those recipes are `command not found` and a few
neighbouring shapes need translating. Everything not listed here applies to
Codex unchanged.

- **Search with `grep -rn 'pattern' <dir>` or `git grep -n 'pattern'`.** Do not
  translate an `rg` recipe flag-for-flag: `-r` means *recursive* in grep and
  *replace* in rg, so a copied `-r` silently rewrites what the search returns
  instead of widening it.
- **Enumerate paths; never pass a shell glob.** The path-glob guard denies an
  unmatched zsh glob before the command runs, and its recovery line names
  `rg --files`. List candidates with `git ls-files` or search a directory you
  have confirmed exists, and use `grep --include` rather than a shell wildcard.
- **Single-quote the whole pattern.** Mixed single/double quoting inside one
  regex is the most frequent denial here; a single-quoted literal avoids both
  zsh expansion and the unmatched-quote refusal.
- **Run lane tests through `yoke watch pytest -- <bare pytest args>`.** A bare
  `python3 -m pytest` inside `.worktrees/<branch>/` resolves the main
  checkout's install: it either fails collection with
  `ModuleNotFoundError: yoke_contracts` or, worse, passes while testing the
  wrong source. `yoke dev run -- <command>` binds any other lane-source command
  the same way.
- **Yoke adapters take `--item PREFIX-N`, never a positional ref.** For example
  `yoke claims work acquire --item PREFIX-N --reason "..."`; the positional form
  is refused.

## Tool use on Codex

Two Codex tool behaviours cost whole turns when they are met for the first
time mid-task. Both are harness-owned: nothing in Yoke changes them, so the
handling is yours.

- **Run a long `yoke` command alone in its own `exec_command`, and keep the
  `session_id` it returns.** A long command shares its call with nothing:
  no `&&` chain, no second command after it, no surrounding pipeline. The
  call returns while the child is still alive, and that returned
  `session_id` is the only handle to it — continue the SAME session with
  `write_stdin` until the command exits and you have read its outcome. A
  second `exec_command` beside a live one spends the shared resource twice
  and can cancel work the first was about to finish, and a turn that ends
  before the child exits kills it with no recorded verdict.
- **Replace a whole file with one `Update` hunk, and re-read a file after
  running a formatter.** `apply_patch` matches context exactly, so a
  rewrite expressed as many hunks fails on the first line that moved, and
  every hunk authored against pre-formatter context is stale the moment a
  formatter, codegen step, or bundle sync rewrites the file. Read the file
  back and author the next patch against what is actually there.

## Identity

The Codex adapter sets these environment variables:

| Variable | Value | Purpose |
|----------|-------|---------|
| `YOKE_EXECUTOR` | `codex` | Identifies this session as a Codex harness |
| `YOKE_PROVIDER` | `openai` | Records the provider for Codex sessions |
| `YOKE_MODEL` | runtime-resolved | Carries the actual Codex model label (for example `gpt-5.4`) into session registration |

The opening hook records these as session identity. Yoke core derives supported paths server-side from the shared registry and applies any limitations declared in the Codex manifest — the harness does not set `YOKE_SUPPORTED_PATHS`. In Codex Desktop, the adapter resolves `YOKE_MODEL` from the current thread's runtime metadata instead of guessing.

## Yoke function-call surface

Yoke control-plane writes (item structured fields, sections, epic-task amendment, DB-claim amendment, claim mutation, QA writes) route through the Yoke function-call surface. Agents call typed function ids (`items.structured_field.replace`, `items.structured_field.append_addendum`, `items.progress_log.append`, `workflow_item.epic_task.body_replace`, `db_claim.amend`, `claims.work.acquire`, etc.); the CLI adapters (`yoke items structured-field replace`, `yoke items structured-field append-addendum`, `yoke items section upsert`, `yoke workflow-item epic-task body-replace`, `yoke db-claim amend`, `yoke claims work acquire`, etc.) construct the matching `FunctionCallRequest` and dispatch through the same registry. See [`.yoke/docs/reference/db-reference/functions.md`](.yoke/docs/reference/db-reference/functions.md) for the envelope, the per-family reference, and the `YokeFunctionCalled` / `DispatcherIdempotencyReplay` / `DispatcherDownstreamDegraded` dispatcher-event schemas.

External tooling (git, pytest, package managers, `rg` / `grep`) stays command-shaped under the permanent-boundary classification. Yoke-owned control-plane reads, writes, and checks are function-shaped.

## What Codex does NOT own

Codex is a harness adapter, not a replacement for Yoke core. The following remain Yoke-core responsibilities:

- **Routing decisions** -- steering selects work and pinned workflow bindings select the stage skill; shared Yoke code owns command/path support and Codex declares only substrate limitations
- **Canonical telemetry** -- session events, lifecycle transitions, and ledger entries come from Yoke core
- **Ownership truth** -- session claims, releases, and ownership tracking are core-owned
- **Safety enforcement** -- correctness comes from Yoke core, not from Codex hooks

Codex hooks (when available) are optional enhancements that improve ergonomics and local visibility. They are never the sole safety layer.

## Lifecycle & Routing

The canonical lifecycle guide is
[.yoke/docs/reference/lifecycle.md](.yoke/docs/reference/lifecycle.md). It explains how immutable
workflow versions own stages, transitions, target-stage gates, policies, and
registered runner bindings. For a live item, read
`yoke workflows item get PREFIX-N` and then
`yoke workflows version get WORKFLOW VERSION`; the pinned definition, not the
guide or a workflow-name branch, is the source of truth for which executor
owns the current stage.

Frontier computation lives in [.yoke/docs/reference/charge-frontier.md](.yoke/docs/reference/charge-frontier.md). Yoke core derives Codex's supported-path set server-side from the shared registry plus any manifest limitations; the adapter does not self-report capabilities via `YOKE_SUPPORTED_PATHS`.

## Related docs

- [Lifecycle & Command Boundaries](.yoke/docs/reference/lifecycle.md) -- canonical human lifecycle guide
- [Charge Frontier](.yoke/docs/reference/charge-frontier.md) -- frontier computation and status-to-adapter map
