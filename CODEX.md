# Yoke -- Codex Harness Guide

This file is the Codex-facing entry point for Yoke. It references the shared bootstrap contract and lists the narrow safe command surface for Codex sessions.

For the full project rules, read `AGENTS.md` (the harness-neutral shared doctrine file; `CLAUDE.md` is retained as a compatibility symlink for harnesses that auto-load it). Everything in `AGENTS.md` applies to Codex sessions unless noted otherwise below.

The `## Simplify — three-axis doctrine` section in `AGENTS.md` defines the shared **reuse / quality / efficiency** vocabulary, future-concept pull-forward lens, and stage weights used by every authoring step (idea, refine, advance, shepherd, conduct, polish). Codex sessions read it from `AGENTS.md`; this file does not duplicate it. The doctrine is Yoke-owned and harness-neutral — do not treat any Claude-only built-in as a dependency.

## Bootstrap

Before doing any work, load the Yoke bootstrap contract. This ensures you have the same orientation context as other supported harness sessions.

### Wrapper-only bootstrap (always works)

Run the entry launcher:

```sh
python3 -m runtime.harness.codex.codex_entry bootstrap
```

This loads:
- `CODEX.md` as the Codex-specific shell
- the neutral startup reads defined by `runtime/harness/bootstrap-spec.json`
- the shared prompt doctrine and startup command output required by the [Harness Bootstrap Contract](docs/harness-bootstrap.md)
- the generated `main_agent` packet block injected by `runtime.harness.bootstrap_packets` so Codex's main session sees the same compact `core` + `claims` schema/API spine the Bash-capable subagents see. Substrate capability truth (hooks, env / session identity, cwd binding, adapter render format, supported commands, parity limits) is documented separately as `harness_contract` in [`docs/harness-bootstrap.md`](docs/harness-bootstrap.md) and [`runtime/harness/manifest-schema.md`](runtime/harness/manifest-schema.md). `harness_contract` is the manifest layer; `main_agent` and `*_agent` are the LLM-facing packet layer — the two never overlap.

### Repo-local skill discovery

Yoke skills live canonically in the hidden directory `.agents/skills/yoke/`. Codex now treats that repo-local `.agents/skills` tree as a native skill source, so no `.codex/skills` mirror or plugin install is required for ordinary Yoke work. Codex progressive disclosure loads each skill's frontmatter first and then reads the full `SKILL.md` only when the skill is invoked.

`.claude/skills/yoke` is a compatibility symlink and must not be treated as the authoritative location. Thin wrappers, docs, and non-native tooling that need to enumerate or resolve Yoke skills should use the Yoke-owned resolver on the existing bootstrap path:

```sh
python3 -m runtime.harness.bootstrap skill-list --root "$YOKE_ROOT"
python3 -m runtime.harness.bootstrap skill-path <skill-name> --root "$YOKE_ROOT"
```

The resolver always returns the canonical `.agents/skills/yoke/.../SKILL.md` path and never falls back to home-directory guesses like `~/.agents` or `~/.codex/skills`. Codex uses the same `SKILL.md` frontmatter Claude reads, so Yoke does not maintain a duplicate `.codex/skills` tree or per-skill Codex metadata sidecars by default. See section 5 of the [Harness Bootstrap Contract](docs/harness-bootstrap.md) for the full contract.

### Hook-enhanced bootstrap (optional, requires Codex >= 0.118.0-alpha.2)

If your Codex build supports `SessionStart` hooks, the bootstrap can be injected automatically in the Codex Desktop app. The proven Desktop setup is:

1. Fully quit and relaunch Codex Desktop.
2. Open the `yoke` repo and start a fresh thread.

Yoke keeps the canonical hook pack at `runtime/harness/codex/hooks.json`, surfaced to Codex via `.codex/hooks.json`. Current Codex builds no longer need a separate feature flag for this.

If you want a source-controlled app launcher, Yoke also provides:

```sh
python3 -m runtime.harness.codex.codex_open_app
```

That opens Codex Desktop on this repo using the app-bundled Codex binary when needed. The wrapper-only path above is always sufficient.

## Ticket intake

Every new backlog item enters through `/yoke idea`. The lower-level item, body, claim, GitHub, and REST creation primitives are internal to that workflow — do not assemble a ticket yourself by chaining `backlog-cli add`, `POST /v1/items`, body writes, path-claim registration, and GitHub sync. The public persistent create surfaces are gated by `yoke_core.domain.ticket_intake_provenance.enforce_public_create_allowed` and reject direct production calls outside sanctioned idea intake with a recovery hint that names `/yoke idea`; dry-run, `--idea-intake` / `provenance="idea"`, and test-isolated DB targets bypass the gate. When you discover a title-only or bypass-created shell, adopt it through `/yoke idea` rather than filling it via lower-level APIs.

## Safe Command Surface

Codex sessions use the shared Yoke operator surface unless the Codex manifest declares a concrete substrate limitation.

### Supported entrypoints

| Command | Description |
|---------|-------------|
| `/yoke idea "title"` | File a new backlog item |
| `/yoke do` | Start an autonomous session (routes through session offer) |
| `/yoke refine YOK-N` | Critique and improve item artifacts (no worktree, no code) |
| `/yoke advance YOK-N implementation` | Issue implementation entry — opens worktree and starts the implementation/review loop |
| `/yoke conduct YOK-N` | Drive an epic through its planned tasks via shared dispatch descriptors |
| `/yoke polish YOK-N` | Review and finish implementation in existing worktree |
| `/yoke usher YOK-N [--dry-run]` | Merge/deploy handoff for implemented items; use dry-run first for Codex validation |

### Supported downstream paths

Codex supports these downstream paths (derived server-side from the shared Yoke registry, then limited by `runtime/harness/codex/manifest.json` only when the manifest declares an explicit limitation):

| Path | Description |
|------|-------------|
| `shepherd` | Drive an item through quality-gated lifecycle to ready |
| `refine` | Critique and improve item artifacts |
| `advance` | Lifecycle transitions, including the issue implementation-entry path |
| `conduct` | Epic execution loop that dispatches Engineer / Tester / Architect / Simulator |
| `polish` | Review and finish implementation in existing worktree |
| `usher` | Merge and deploy implemented/release items through the top-level operator flow |

Work requiring paths outside this shared delivery-path set still falls back with a clear message. Yoke core derives the path list from the shared registry plus manifest-declared limitations — the harness no longer self-reports capabilities via environment variables.

### Limitations

The Codex manifest at `runtime/harness/codex/manifest.json` is the source of truth for substrate limitations and currently declares none on entrypoints or downstream paths. The full Tier 1 operator surface listed in [`docs/harness-bootstrap.md`](docs/harness-bootstrap.md) §2 — including `/yoke conduct`, `/yoke freeze`, `/yoke thaw`, `/yoke resync`, `/yoke curate`, `/yoke wrapup`, `/yoke feed`, `/yoke strategize`, and `/yoke charge` — is part of Codex's safe surface. Conduct dispatches the same `yoke-engineer`, `yoke-tester`, `yoke-architect`, and `yoke-simulator` agent bodies as Claude, rendered into Codex custom agents at `runtime/harness/codex/agents/yoke-*.toml` and surfaced to Codex at `.codex/agents/yoke-*.toml` from the canonical bodies under `runtime/agents/`. The shared dispatch descriptor module emits the same task envelope for both harnesses, so phase files name agents through descriptors rather than a Claude-only `subagent_type`. Result ingestion is parseable on both sides, and tool-call telemetry flows into the same event stream.

The remaining named substrate gap is on the telemetry edge: Codex does not emit a dedicated `PostToolUseFailure` event for non-Bash tools (Write/Edit/Read). Bash failures on Codex are recovered inside the `PostToolUse` handler via exit-code parsing, hard-failure text matching, and last-resort transcript reconciliation against `tool_use_id` ↔ rollout `call_id`. See [`docs/hook-parity-map.md`](docs/hook-parity-map.md) for the tier-by-tier breakdown.

Future shared-registry additions inherit to Codex unless a real substrate limitation is declared in the manifest.

## Identity

The Codex adapter sets these environment variables:

| Variable | Value | Purpose |
|----------|-------|---------|
| `YOKE_EXECUTOR` | `codex` | Identifies this session as a Codex harness |
| `YOKE_PROVIDER` | `openai` | Makes the shared `/yoke do` session offer truthful for Codex runs |
| `YOKE_MODEL` | runtime-resolved | Carries the actual Codex model label (for example `gpt-5.4`) into the session offer |

These are consumed by `/yoke do` to construct the session offer with correct harness identity. Yoke core derives supported paths server-side from the shared registry and applies any limitations declared in `runtime/harness/codex/manifest.json` — the harness does not set `YOKE_SUPPORTED_PATHS`. In Codex Desktop, the adapter resolves `YOKE_MODEL` from the current thread's runtime metadata instead of guessing.

If you need sourceable exports for a shell-managed wrapper, run:

```sh
eval "$(python3 -m runtime.harness.codex.codex_entry env)"
```

The launcher can print or export the identity contract, but it cannot retroactively mutate the parent prompt runtime after it exits. Prompt-managed `/yoke` commands should carry the same identity values explicitly.

## Yoke function-call surface

Yoke control-plane writes (item structured fields, sections, epic-task amendment, DB-claim amendment, claim mutation, QA writes) route through the Yoke function-call surface in `yoke_core.domain.yoke_function_dispatch`. Agents call typed function ids (`items.structured_field.replace`, `items.structured_field.append_addendum`, `items.progress_log.append`, `workflow_item.epic_task.body_replace`, `db_claim.amend`, `claims.work.acquire`, etc.); the CLI adapters (`yoke items structured-field replace`, `yoke items structured-field append-addendum`, `yoke items section upsert`, `yoke workflow-item epic-task body-replace`, `yoke db-claim amend`, `yoke claims work acquire`, etc.) construct the matching `FunctionCallRequest` and dispatch through the same registry. See [`docs/db-reference/functions.md`](docs/db-reference/functions.md) for the envelope and per-family reference, [`docs/atlas.md`](docs/atlas.md) for the operator-readable Atlas of every `yoke` subcommand + permanent boundary + pending row, and [`docs/event-catalog.md`](docs/event-catalog.md) for the `YokeFunctionCalled` / `DispatcherIdempotencyReplay` / `DispatcherDownstreamDegraded` envelope schemas.

External tooling (git, pytest, package managers, `rg` / `grep`) stays command-shaped under the permanent-boundary classification documented in [`docs/atlas.md`](docs/atlas.md). Yoke-owned control-plane reads, writes, and checks are function-shaped.

## What Codex does NOT own

Codex is a harness adapter, not a replacement for Yoke core. The following remain Yoke-core responsibilities:

- **Routing decisions** -- `/yoke do` decides what to do next; shared Yoke code owns command/path support and Codex declares only substrate limitations
- **Canonical telemetry** -- session events, lifecycle transitions, and ledger entries come from Yoke core
- **Ownership truth** -- session claims, releases, and ownership tracking are core-owned
- **Safety enforcement** -- correctness comes from Yoke core, not from Codex hooks

Codex hooks (when available) are optional enhancements that improve ergonomics and local visibility. They are never the sole safety layer.

## Manifest

The Codex capability manifest is at `runtime/harness/codex/manifest.json`. It declares adapter identity, runtime affordances, telemetry posture, and explicit limitations. It does not copy the shared Yoke command/path list.

## Lifecycle & Routing

The canonical lifecycle guide is [docs/lifecycle.md](docs/lifecycle.md). It defines the issue and epic progressions, the command boundaries for `refine` / `shepherd` / `advance` / `conduct` / `polish` / `usher`, and how review loops operate inside a worktree. Read it once at bootstrap and treat it as the source of truth for "which command moves which status" before guessing from derivative docs.

Routing for `/yoke do` (session offer, `NextAction` directives, chainability, supported-path derivation) lives in [docs/session-offer-contract.md](docs/session-offer-contract.md) and [docs/charge-frontier.md](docs/charge-frontier.md). Yoke core derives Codex's supported-path set server-side from the shared registry plus any limitations in `runtime/harness/codex/manifest.json`; the adapter does not self-report capabilities via `YOKE_SUPPORTED_PATHS`.

## Related docs

- [Lifecycle & Command Boundaries](docs/lifecycle.md) -- canonical human lifecycle guide
- [Session-Offer Contract](docs/session-offer-contract.md) -- `/yoke do` request/response shape
- [Charge Frontier](docs/charge-frontier.md) -- frontier computation and status-to-adapter map
- [Harness Bootstrap Contract](docs/harness-bootstrap.md) -- neutral startup expectations
- [Harness Adapter Template](docs/harness-adapter-template.md) -- five-part adapter template
- [Harness README](runtime/harness/README.md) -- adapter directory convention
