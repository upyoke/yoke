# Yoke -- Cursor Harness Guide
<!-- BEGIN YOKE MANAGED BLOCK -->
<!-- Managed by `yoke project install`. Everything between the BEGIN and END markers is overwritten on refresh — do not edit it here. Your own content outside the markers is always preserved. -->
This file is the Cursor-facing entry point for Yoke. It references the shared bootstrap contract and lists the safe command surface for Cursor sessions.

For the full project rules, read `AGENTS.md` — the harness-neutral shared doctrine file. Cursor loads `AGENTS.md` natively (including nested per-directory `AGENTS.md`), so everything there applies to Cursor sessions unless noted otherwise below. In this repo `CLAUDE.md` is a symlink to `AGENTS.md`; in a managed project they are separate real files, so content outside the managed markers must be added to each shell or the other harnesses never see it.

The `## Simplify — three-axis doctrine` section in `AGENTS.md` defines the shared **reuse / quality / efficiency** vocabulary; this file does not duplicate it. The doctrine is Yoke-owned and harness-neutral — do not treat any Claude-only built-in as a dependency.

## Bootstrap

Cursor loads `AGENTS.md` automatically. The session-start hook (wired in `.cursor/hooks.json`) injects the Yoke orientation and the generated `main_agent` packet block through the `sessionStart` hook's `additional_context` output — the same compact `core` + `claims` schema/API spine other supported harness sessions receive. Substrate capability truth (hooks, identity, cwd binding, adapter render format, supported commands, parity limits) is documented as `harness_contract` in [`docs/harness-bootstrap.md`](docs/harness-bootstrap.md); the measured substrate mapping lives in [`docs/harness-cursor-assessment.md`](docs/harness-cursor-assessment.md).

### Repo-local skill discovery

Yoke skills live canonically in `.agents/skills/yoke/`. Cursor discovers that tree natively (measured on Cursor IDE 3.14+ and cursor-agent 2026.07+), so no `.cursor/skills` mirror is required for ordinary Yoke work. Skills surface in the `/` menu and via description-based invocation; `.claude/skills/yoke` remains the Claude discovery copy and is not authoritative.

## Surfaces

Cursor sessions run on two surfaces with different hook coverage:

| Surface | Discriminator | Hook coverage |
|---------|---------------|---------------|
| IDE agent chat | `CURSOR_INVOKED_AS` unset in hook env | Full event set, including `beforeSubmitPrompt`, `stop`, `subagentStart`/`subagentStop`, `afterFileEdit` |
| `cursor-agent` CLI (`-p` non-interactive) | `CURSOR_INVOKED_AS=cursor-agent` | Lifecycle + tool events only; no prompt-submit, stop, or subagent lifecycle events |

Orientation and policy enforcement anchor on events both surfaces fire: `sessionStart` (orientation via `additional_context`) and `beforeShellExecution`/`preToolUse` (gates — a hook deny holds even under `--force`).

## Identity

Cursor exports no session-id environment variable. Identity facts:

| Signal | Source | Purpose |
|--------|--------|---------|
| `session_id` / `conversation_id` | every hook payload (stdin) | Session identity (identical values) |
| `CURSOR_TRANSCRIPT_PATH` | hook process env | Top-level (container) session recovery — points at the main session's transcript even inside subagent hooks |
| `parent_conversation_id` | `subagentStart`/`subagentStop` payloads | Explicit subagent → container lineage |
| `YOKE_EXECUTOR=cursor` | pinned in the generated hook command | Family attribution regardless of env inheritance |
| `model` / `model_id` | every hook payload | Model attribution — Cursor multiplexes providers, so the payload is the only truthful model source |

Yoke's container model applies: only the top-level session registers as a `harness_sessions` row; subagent activity (which arrives under per-subagent session ids) folds into that container.

## What Cursor does NOT own

Cursor is a harness adapter, not a replacement for Yoke core. Routing decisions, canonical telemetry, ownership truth, and safety enforcement remain Yoke-core responsibilities. Cursor hooks are enhancements and never the sole safety layer. Cursor-native features that overlap Yoke-owned mechanics stay unused by Yoke flows: `cursor-agent`'s worktree flags (`-w`, `--worktree-base`) — Yoke owns worktree placement; the `stop` hook's `followup_message` loop channel — Yoke's session chaining is core-owned; Cloud Agent handoff (`&`) — Yoke sessions are local.

## Operational cautions

- `.cursor/cli.json` requires `permissions.allow` (an allow-less deny-only file aborts every run before the agent starts) — the same all-or-nothing failure class as Claude's `settings.json`.
- Interactive `cursor-agent` gates on a Workspace Trust prompt; automation passes `--trust`. Non-interactive `-p` runs do not prompt.
- The IDE's bundled `cursor agent` launcher auto-installs the `cursor-agent` binary when absent; install it deliberately during onboarding rather than as a side effect.

## Lifecycle & Routing

The canonical lifecycle guide is [.yoke/docs/lifecycle.md](.yoke/docs/lifecycle.md). For a live item, read `yoke workflows item get PREFIX-N` then `yoke workflows version get WORKFLOW VERSION`; the pinned definition is the source of truth for which executor owns the current stage. Routing for `/yoke do` lives in [.yoke/docs/session-offer-contract.md](.yoke/docs/session-offer-contract.md) and [.yoke/docs/charge-frontier.md](.yoke/docs/charge-frontier.md). Yoke core derives Cursor's supported-path set server-side from the shared registry plus any limitations declared in the Cursor manifest; the adapter does not self-report capabilities.

## Related docs

- [Cursor Harness Integration Assessment](docs/harness-cursor-assessment.md) -- measured substrate mapping
- [Harness Bootstrap Contract](docs/harness-bootstrap.md) -- neutral startup expectations
- [Harness Adapter Template](docs/harness-adapter-template.md) -- five-part adapter template
- [Hook Parity Map](docs/hook-parity-map.md) -- hook classification across harnesses
<!-- END YOKE MANAGED BLOCK -->
