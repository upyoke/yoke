# Yoke -- Codex Harness Guide
<!-- BEGIN YOKE MANAGED BLOCK -->
<!-- Managed by `yoke project install`. Everything between the BEGIN and END markers is overwritten on refresh — do not edit it here. Your own content outside the markers is always preserved. -->
This file is the Codex-facing entry point for Yoke. It references the shared bootstrap contract and lists the narrow safe command surface for Codex sessions.

For the full project rules, read `AGENTS.md` — the harness-neutral shared doctrine file, and the one Codex loads. `CLAUDE.md` carries the same Yoke-managed block for Claude, which reads that file and does not fall back to `AGENTS.md`. In this repo the two are one file behind a symlink; in a managed project they are two real files, so anything written outside the managed markers has to be added to both or one harness never sees it. Everything in `AGENTS.md` applies to Codex sessions unless noted otherwise below.

The `## Simplify — three-axis doctrine` section in `AGENTS.md` defines the shared **reuse / quality / efficiency** vocabulary, future-concept pull-forward lens, and stage weights used by every authoring step (idea, refine, advance, shepherd, conduct, polish). Codex sessions read it from `AGENTS.md`; this file does not duplicate it. The doctrine is Yoke-owned and harness-neutral — do not treat any Claude-only built-in as a dependency.

## Bootstrap

Codex loads its Yoke orientation automatically from the auto-loaded rules files (`AGENTS.md` shared doctrine + this `CODEX.md` shell) plus the session-start hook, which injects the same orientation and the generated `main_agent` packet block other supported harness sessions receive. That gives Codex's main session the same compact `core` + `claims` schema/API spine the Bash-capable subagents see. Substrate capability truth (hooks, env / session identity, cwd binding, adapter render format, supported commands, parity limits) is documented separately as the `harness_contract` manifest, which the Codex adapter carries alongside this shell. `harness_contract` is the manifest layer; `main_agent` and `*_agent` are the LLM-facing packet layer — the two never overlap.

### Repo-local skill discovery

Yoke skills live canonically in the hidden directory `.agents/skills/yoke/`. Codex treats that repo-local `.agents/skills` tree as a native skill source, so no `.codex/skills` mirror or plugin install is required for ordinary Yoke work. Codex progressive disclosure loads each skill's frontmatter first and reads the full `SKILL.md` only when the skill is invoked. `.claude/skills/yoke` is a discovery copy — a symlink in this repo, a real byte-identical copy in a managed project, since installs cannot rely on symlink support — and must not be treated as the authoritative location; Codex reads the same `SKILL.md` frontmatter Claude reads, so Yoke keeps no duplicate `.codex/skills` tree or per-skill Codex metadata sidecars.

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

## Work-item entry surfaces

Every create selects a workflow and a typed entry surface (`web_form`, `cli`, `harness_skill`, or `promotion`); the pinned immutable workflow version must allow that surface. `/yoke idea` drives the registered `items.create` function through `harness_skill`, while product forms and operator commands use their own typed surfaces. Dry-run and test-isolated DB targets may omit the surface.

## Safe Command Surface

Codex sessions use the shared Yoke operator surface unless the Codex manifest declares a concrete substrate limitation.

### Supported entrypoints

| Command | Description |
|---------|-------------|
| `/yoke idea "title"` | File a new backlog item |
| `/yoke do` | Start an autonomous session (routes through session offer) |
| `/yoke refine PREFIX-N` | Critique and improve item artifacts (no worktree, no code) |
| `/yoke advance PREFIX-N implementation` | Drive a pinned `advance` segment in its registered single worktree lane |
| `/yoke conduct PREFIX-N` | Drive a pinned generated-task segment via shared dispatch descriptors |
| `/yoke polish PREFIX-N` | Review and finish implementation in existing worktree |
| `/yoke usher PREFIX-N [--dry-run]` | Merge/deploy handoff for implemented items; use dry-run first for Codex validation |

### Supported downstream paths

Codex supports these downstream paths (derived server-side from the shared Yoke registry, then limited by the Codex manifest only when the manifest declares an explicit limitation):

| Path | Description |
|------|-------------|
| `shepherd` | Drive an item through quality-gated lifecycle to ready |
| `refine` | Critique and improve item artifacts |
| `advance` | Definition-bound single-lane lifecycle execution |
| `dash` | Instruction-sized direct execution: survey, worktree, verify, merge, evidence |
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

## Identity

The Codex adapter sets these environment variables:

| Variable | Value | Purpose |
|----------|-------|---------|
| `YOKE_EXECUTOR` | `codex` | Identifies this session as a Codex harness |
| `YOKE_PROVIDER` | `openai` | Makes the shared `/yoke do` session offer truthful for Codex runs |
| `YOKE_MODEL` | runtime-resolved | Carries the actual Codex model label (for example `gpt-5.4`) into the session offer |

These are consumed by `/yoke do` to construct the session offer with correct harness identity. Yoke core derives supported paths server-side from the shared registry and applies any limitations declared in the Codex manifest — the harness does not set `YOKE_SUPPORTED_PATHS`. In Codex Desktop, the adapter resolves `YOKE_MODEL` from the current thread's runtime metadata instead of guessing.

## Yoke function-call surface

Yoke control-plane writes (item structured fields, sections, epic-task amendment, DB-claim amendment, claim mutation, QA writes) route through the Yoke function-call surface. Agents call typed function ids (`items.structured_field.replace`, `items.structured_field.append_addendum`, `items.progress_log.append`, `workflow_item.epic_task.body_replace`, `db_claim.amend`, `claims.work.acquire`, etc.); the CLI adapters (`yoke items structured-field replace`, `yoke items structured-field append-addendum`, `yoke items section upsert`, `yoke workflow-item epic-task body-replace`, `yoke db-claim amend`, `yoke claims work acquire`, etc.) construct the matching `FunctionCallRequest` and dispatch through the same registry. See [`.yoke/docs/reference/db-reference/functions.md`](.yoke/docs/reference/db-reference/functions.md) for the envelope, the per-family reference, and the `YokeFunctionCalled` / `DispatcherIdempotencyReplay` / `DispatcherDownstreamDegraded` dispatcher-event schemas.

External tooling (git, pytest, package managers, `rg` / `grep`) stays command-shaped under the permanent-boundary classification. Yoke-owned control-plane reads, writes, and checks are function-shaped.

## What Codex does NOT own

Codex is a harness adapter, not a replacement for Yoke core. The following remain Yoke-core responsibilities:

- **Routing decisions** -- `/yoke do` decides what to do next; shared Yoke code owns command/path support and Codex declares only substrate limitations
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

Routing for `/yoke do` (session offer, `NextAction` directives, chainability, supported-path derivation) lives in [.yoke/docs/reference/session-offer.md](.yoke/docs/reference/session-offer.md) and [.yoke/docs/reference/charge-frontier.md](.yoke/docs/reference/charge-frontier.md). Yoke core derives Codex's supported-path set server-side from the shared registry plus any manifest limitations; the adapter does not self-report capabilities via `YOKE_SUPPORTED_PATHS`.

## Related docs

- [Lifecycle & Command Boundaries](.yoke/docs/reference/lifecycle.md) -- canonical human lifecycle guide
- [Session-Offer Contract](.yoke/docs/reference/session-offer.md) -- `/yoke do` request/response shape
- [Charge Frontier](.yoke/docs/reference/charge-frontier.md) -- frontier computation and status-to-adapter map
<!-- END YOKE MANAGED BLOCK -->

# Yoke Repo Internals (Codex)
<!-- Not shipped to managed projects — specific to the yoke source repo. The managed block above is the project-agnostic Codex shell `yoke project install` ships; the wrappers and source paths below are yoke-source-dev plumbing. -->

## Harness contract references (yoke source dev)

These describe how Yoke's harness adapters are built and compared. They live in
`docs/`, which the install bundle does not ship, so they stay out of the managed
block above:

- [Harness Bootstrap Contract](docs/harness-bootstrap.md) -- neutral startup expectations; §2 lists the full Tier 1 operator surface
- [Harness Adapter Template](docs/harness-adapter-template.md) -- five-part adapter template
- [Hook Parity Map](docs/hook-parity-map.md) -- tier-by-tier hook classification across harnesses, including the Codex `PostToolUseFailure` gap

## Bootstrap render (yoke source dev)

Hooks inject orientation at session start. To print the full bootstrap
without relying on hook injection:

```sh
python3 -m yoke_core.hooks.bootstrap render-full --spec runtime/harness/bootstrap-spec.json --root .
```

That loads `CODEX.md` as the Codex-specific shell, the neutral startup reads
defined by `runtime/harness/bootstrap-spec.json`, the shared prompt doctrine
and startup command output required by the [Harness Bootstrap
Contract](docs/harness-bootstrap.md), and the generated `main_agent` packet
block injected by `yoke_core.domain.main_agent_packet`.

Codex Desktop opens this repo directly:

```sh
codex app .
```

Session identity comes from the hook pack: `.codex/hooks.json` sets
`YOKE_EXECUTOR` and `YOKE_PROVIDER` on every hook invocation, and the model
and entrypoint resolve from the Codex runtime. Nothing needs to be exported
into the shell by hand.

## Skill resolver (yoke source dev)

Thin wrappers, docs, and non-native tooling that need to enumerate or resolve Yoke skills use the Yoke-owned resolver on the bootstrap path:

```sh
python3 -m yoke_core.hooks.bootstrap skill-list --root "$YOKE_ROOT"
python3 -m yoke_core.hooks.bootstrap skill-path <skill-name> --root "$YOKE_ROOT"
```

The resolver always returns the canonical `.agents/skills/yoke/.../SKILL.md` path and never falls back to home-directory guesses like `~/.agents` or `~/.codex/skills`.

## Hook pack & manifest (source layout)

Yoke keeps the canonical Codex hook pack at `runtime/harness/codex/hooks.json`, surfaced to Codex via `.codex/hooks.json`; current Codex builds inject the session-start bootstrap automatically. The Codex capability manifest is at `runtime/harness/codex/manifest.json` — it declares adapter identity, runtime affordances, telemetry posture, and explicit limitations, and does not copy the shared Yoke command/path list. Conduct renders the shared agent bodies into Codex custom agents at `runtime/harness/codex/agents/yoke-*.toml`, surfaced at `.codex/agents/yoke-*.toml` from the canonical bodies under `runtime/agents/`. Adapter directory convention: [Harness README](runtime/harness/README.md).
