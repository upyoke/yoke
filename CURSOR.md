# Yoke -- Cursor Harness Guide
<!-- BEGIN YOKE MANAGED BLOCK -->
<!-- Managed by `yoke project install`. Everything between the BEGIN and END markers is overwritten on refresh — do not edit it here. Your own content outside the markers is always preserved. -->
This file is the Cursor-facing entry point for Yoke. It references the shared bootstrap contract and lists the safe command surface for Cursor sessions.

For the full project rules, read `AGENTS.md` — the harness-neutral shared doctrine file. Cursor loads `AGENTS.md` natively (including nested per-directory `AGENTS.md`), so everything there applies to Cursor sessions unless noted otherwise below. In this repo `CLAUDE.md` is a symlink to `AGENTS.md`; in a managed project they are separate real files, so content outside the managed markers must be added to each shell or the other harnesses never see it.

The `## Simplify — three-axis doctrine` section in `AGENTS.md` defines the shared **reuse / quality / efficiency** vocabulary; this file does not duplicate it. The doctrine is Yoke-owned and harness-neutral — do not treat any Claude-only built-in as a dependency.

## Bootstrap

Cursor loads `AGENTS.md` automatically. The session-start hook (wired in `.cursor/hooks.json`) injects the Yoke orientation and the generated `main_agent` packet block through the `sessionStart` hook's `additional_context` output — the same compact `core` + `claims` schema/API spine other supported harness sessions receive. Substrate capability truth (hooks, identity, cwd binding, adapter render format, supported commands, parity limits) is documented as the `harness_contract` manifest, which the Cursor adapter carries alongside this shell.

`.cursor/hooks.json` is the primary project-policy hook owner in Cursor. Cursor may also list compatible entries discovered in the regular `.claude/settings.json` file when third-party config import is enabled; with matched Cursor process/payload provenance they defer only to a valid matching native owner and otherwise remain the compatibility path. For stop/sessionEnd the order is native project hook, machine-local backstop, then Claude compatibility, so one owner dispatches even after a worktree is deleted or a project config is missing. Project refresh and source-dev setup materialize both Cursor-scanned files and migrate legacy in-repo symlinks.

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
| `CURSOR_CONVERSATION_ID` | agent shell env | The conversation that spawned a shell — a subagent shell carries its OWN id, so this is not a session id until mapped |
| `YOKE_EXECUTOR=cursor` | pinned in the generated hook command | Family attribution regardless of env inheritance |
| `model` / `model_id` | every hook payload | Model attribution — Cursor multiplexes providers, so the payload is the only truthful model source |

Yoke's container model applies: only the top-level session registers as a `harness_sessions` row; subagent activity (which arrives under per-subagent session ids) folds into that container. The same fold applies when Cursor remounts a chat onto a linked Yoke worktree (new conversation id under `.worktrees/<lane>`): the new conversation aliases to the session that holds the active work claim for that lane, via `cursor-session-map`, instead of minting competing authority.

Commands the agent runs in a shell resolve identity through that same container. The process-anchor registry cannot help — one `cursor-agent` pid hosts every conversation, so an anchor keyed on it would resolve to whichever sibling wrote last — and `CURSOR_CONVERSATION_ID` alone names a conversation, not a registered session. So every hook records its `conversation_id → container session` pairing under `<machine-home>/cursor-session-map/`, and a shell resolves its own conversation id through that recording. A conversation no hook has recorded resolves to nothing rather than to a guess.

The conversation map is established on the first client hook (`preToolUse` / `beforeShellExecution` / `sessionStart`), not only `sessionStart`. Stay-on-main with absolute `.worktrees/<lane>/...` paths is the supported posture (same conversation id). Switching back to main with a new conversation id and no transcript / parent / already-mapped alias is a new session — do not guess a unique live claim holder on that repo.

**Do not root the Cursor chat on a Yoke worktree.** Keep the agent on the main project checkout and use absolute `worktree_path` values for lane work. Do not call `move_agent_to_root` into `.worktrees/...`. Remounting triggers the conversation remap above; after merge removes the lane, Cursor's sticky cwd/root also leaves Shell failing with `ENOENT` on the deleted path. Pass an explicit live `working_directory` when needed. Yoke still owns worktree placement (`cursor-agent` `-w` / `--worktree-base` stay unused).

**Stop/sessionEnd must still run when the project root is gone.** Cursor project hooks spawn with cwd = project root; a deleted `.worktrees/<lane>` makes that spawn fail, so session-end cleanup never reaches Yoke. Lifecycle hook commands peel a missing worktree path to the parent checkout, emit Cursor-safe `{}` on allow, and a machine-local `~/.cursor/hooks.json` backstop (installed on Cursor hook traffic) runs the same stop/sessionEnd evaluate from `~/.cursor`, which always exists.

## What Cursor does NOT own

Cursor is a harness adapter, not a replacement for Yoke core. Routing decisions, canonical telemetry, ownership truth, and safety enforcement remain Yoke-core responsibilities. Cursor hooks are enhancements and never the sole safety layer. Cursor-native features that overlap Yoke-owned mechanics stay unused by Yoke flows: `cursor-agent`'s worktree flags (`-w`, `--worktree-base`) — Yoke owns worktree placement; Cloud Agent handoff (`&`) — Yoke sessions are local. The `stop` hook's `followup_message` loop channel is reserved for one self-continuation: when the promised-work gate holds a turn open because this session still has uncalled work. That is not operator-to-session steering.

## Approvals and the network sandbox

Cursor decides whether an agent command runs unprompted at three layers. Two are project files Yoke installs and keeps merged; the third is machine-level and yours to set. Getting only the first two right still leaves you approving commands one at a time.

| Layer | Where | Who owns it |
|-------|-------|-------------|
| Command approvals | `.cursor/cli.json` → `permissions.allow` | Yoke installs and merges its region |
| Network sandbox | `.cursor/sandbox.json` → `networkPolicy` | Yoke installs and merges its region |
| Approval / execution mode | Cursor's own settings (Approvals, Execution mode) | You — no project file can reach it |

**Recommended posture: zero prompts.** Set Execution mode to **Run Everything**. That matches how Yoke machines already run every other harness, and the rationale is the same: Yoke owns enforcement through its `PreToolUse` hook chain and lint fleet, so a harness approval prompt is redundant friction rather than a safety layer. Hooks keep firing in this mode — a hook deny holds even under `--force`. If you prefer to keep Auto-review, the closest zero-prompt composite is `yoke *`, `git *`, and `gh *` in the command allowlist plus a network mode that allows the origins already listed in `.cursor/sandbox.json`.

Confirm your chosen mode on the first session of a new machine: run one network-touching `yoke` read and check that it completes with no prompt **and** that hook telemetry recorded the call. `yoke doctor` reports the machine-level posture it can see (`HC-cursor-approval-posture`) and prints the exact settings to change.

**Do not request full-network permission.** Cursor treats an explicit `required_permissions: full_network` request as an escalation and prompts even for hosts the network policy already allows. Once `.cursor/sandbox.json` allows the control-plane origins, retry inside the sandbox instead — requesting the escalation causes the very per-command prompting these files exist to remove.

**Explicit non-choices.** The `all` permission tier is never the answer: it disables the sandbox wholesale, filesystem included, which is strictly broader than the zero-prompt posture needs. Yoke's installed regions default `networkPolicy.default` to `deny` and allow only this machine's configured control-plane and GitHub endpoints — resolved from machine config, so a self-hosted or differently-tenanted installation allows its own origins.

Both files are regular files, never symlinks (Cursor refuses project config paths containing symlinks). Yoke unions its entries in and never removes or reorders yours; `yoke project install` — or `yoke dev setup` in a Yoke source checkout — reapplies them idempotently, and `HC-cursor-permission-config` reports a missing or emptied region.

## Operational cautions

- `.cursor/cli.json` requires `permissions.allow` (an allow-less deny-only file aborts every run before the agent starts) — the same all-or-nothing failure class as Claude's `settings.json`.
- Interactive `cursor-agent` gates on a Workspace Trust prompt; automation passes `--trust`. Non-interactive `-p` runs do not prompt.
- The IDE's bundled `cursor agent` launcher auto-installs the `cursor-agent` binary when absent; install it deliberately during onboarding rather than as a side effect.

## Lifecycle & Routing

The canonical lifecycle guide is [.yoke/docs/reference/lifecycle.md](.yoke/docs/reference/lifecycle.md). For a live item, read `yoke workflows item get PREFIX-N` then `yoke workflows version get WORKFLOW VERSION`; the pinned definition is the source of truth for which executor owns the current stage. Routing for `/yoke do` lives in [.yoke/docs/reference/session-offer.md](.yoke/docs/reference/session-offer.md) and [.yoke/docs/reference/charge-frontier.md](.yoke/docs/reference/charge-frontier.md). Yoke core derives Cursor's supported-path set server-side from the shared registry plus any limitations declared in the Cursor manifest; the adapter does not self-report capabilities.

<!-- END YOKE MANAGED BLOCK -->

# Yoke Repo Internals (Cursor)
<!-- Not shipped to managed projects — specific to the yoke source repo. The managed block above is the project-agnostic Cursor shell `yoke project install` ships; the harness-build references below are yoke-source-dev material. -->

## Harness contract references (yoke source dev)

These describe how Yoke's harness adapters are built, measured, and compared.
They live in `docs/`, which the install bundle does not ship, so they stay out
of the managed block above:

- [Cursor Harness Integration Assessment](docs/harness-cursor-assessment.md) -- measured substrate mapping for Cursor
- [Harness Bootstrap Contract](docs/harness-bootstrap.md) -- neutral startup expectations
- [Harness Adapter Template](docs/harness-adapter-template.md) -- five-part adapter template
- [Hook Parity Map](docs/hook-parity-map.md) -- hook classification across harnesses
