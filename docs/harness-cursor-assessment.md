# Cursor Harness Integration Assessment

*Feasibility and parity assessment for integrating Cursor as a third Yoke
harness alongside Claude Code and Codex. Cursor is **not yet a supported
harness**; this document records what its substrate offers, how each
Yoke-handled axis maps, and what remains open. Companion docs:
[Harness Adapter Template](harness-adapter-template.md),
[Harness Substrate](harness-substrate.md),
[Hook Parity Map](hook-parity-map.md),
[Manifest Schema](../runtime/harness/manifest-schema.md).*

*Measured basis: Cursor IDE 3.14.7 and `cursor-agent` 2026.07.23-e383d2b on
macOS, via a disposable project carrying a `.cursor/hooks.json` that wired
every documented hook event to a logging command — one non-interactive CLI run
(`cursor-agent -p … --force`, 46 hook invocations), one IDE agent-chat run
(44 invocations), plus probe subagents, a probe skill, and sentinel-token
context-injection checks. Re-verify against newer Cursor builds before
implementation; hook payloads and event coverage are vendor-owned.*

## Verdict summary

- **Hook denials are a real policy boundary.** A `beforeShellExecution` deny
  blocked the agent's command *with `--force` active*; the model received the
  structured `agent_message` and did not retry; `postToolUseFailure` fired
  with `failure_type=permission_denied`.
- **Zero enablement ceremony.** A project `.cursor/hooks.json` fired on the
  first run in a directory never opened in the IDE — no approval step (Codex
  requires in-app hook approval; Claude requires the settings schema).
- **Context injection works where Yoke needs it**: `sessionStart` and
  `postToolUse` both accepted `additional_context` (measured; the vendor's
  own on-disk hook guide omits `sessionStart` from its output cheat sheet).
- **Discovery is free**: `AGENTS.md`, `.agents/skills/`, `.cursor/agents/`,
  and `.claude/agents/` (including tolerated Claude-only frontmatter keys)
  all resolved without configuration.
- **The cost is on Yoke's side**: harness identity is a hardcoded two-member
  vocabulary across many core modules (inventory below), so a third harness
  is a core change, not a template instantiation.

## Harness vocabulary and core enumeration sites

Claude and Codex are enumerated in code, not discovered. Every site below
needs a third member (or a registry seam) before any Cursor adapter can
exist. Ids in play: directory `runtime/harness/{id}/`, canonical executor id
(`claude-code` / `codex` style), and the short conditional-block id
(`claude` / `codex`) — note the existing two-vocabulary split.

| Surface | Module |
|---|---|
| `CANONICAL_HARNESS_IDS`, `EXECUTOR_EMOJI` (drives `KNOWN_EXECUTOR_LABELS` / surface labels) | `yoke_contracts.executor_labels` |
| `HARNESS_UNIVERSE` (default `OperatorCommand.harness_support`) | `yoke_core.domain.harness_capability_registry` |
| `HARNESS_IDS` for `<!-- YOKE:HARNESS <id> -->` blocks | `yoke_core.domain.agents_render_conditional` |
| `CLAUDE_MANIFEST` / `CODEX_MANIFEST` source dicts | `yoke_core.domain.agents_render_manifests` |
| `_MANIFEST_DIRECTORY_BY_HARNESS_ID` (capability resolution) | `yoke_core.domain.sessions_queries_lookup` |
| `render_for_harness` explicit per-harness branches | `yoke_core.domain.dispatch_descriptors` |
| Executor/provider/entrypoint detection — **two duplicated copies** | `yoke_core.hooks.helpers_identity` and `yoke_harness.hooks.identity_runtime` |
| `AMBIENT_ENV_VARS` session-id env chain | `yoke_core.domain.session_ambient_identity` |
| `HARNESS_PROCESS_BASENAMES` / `MULTIPLEXED_PROCESS_BASENAMES` | `yoke_contracts.process_ancestry` |
| Binary family fallback (`codex` prefix else `claude`) — an unknown executor silently inherits Claude's wire format | `yoke_core.hooks.capability_resolve` |
| `render_claude_decision` / `render_codex_decision` wire formats | `yoke_core.hooks.decision_render` |
| Per-family lifecycle branches (orientation, stop shape, env delivery) | `yoke_core.hooks.session_dispatch` |
| Hook-block renderers + `_CODEX_VERB_BY_EVENT` + identity env pin | `yoke_core.domain.agents_render_hooks` |
| `SETTINGS_FILE_BY_HOOKS_KEY`, `HOOK_MERGE_TARGETS`, bundle hook-key validation | `yoke_cli.project_install` (`hooks.py`, `files.py`, `validate.py`) |
| `INSTALL_BUNDLE_SOURCE_DIRS` | `yoke_core.domain.install_bundle` |
| Rendered packet text naming the `harness_id` enum | `yoke_core.domain.schema_api_context_render` (+ claims-table stanza) |
| Canonical-session-id gate for known harnesses | `yoke_core.api.service_client_sessions_offer` |

`AdapterCapability` (`yoke_core.hooks.adapter_capability`) is
the designed plug seam — payload parser, decision renderer, chain omissions —
and a Cursor integration authors one instance plus the surrounding
enumeration edits above.

## Hook events: mapping and measured coverage

Cursor config: project `.cursor/hooks.json` (`{"version": 1, "hooks": {…}}`),
user `~/.cursor/hooks.json`; watched and hot-reloaded; matchers are
JavaScript regexes over tool type, shell command, or subagent type. Exit 0 +
JSON output, or exit 2 to block; `failClosed` opts a hook into
deny-on-crash; per-entry `timeout` (seconds) bounds execution — unset
entries inherit an undocumented platform default, so the rendered Yoke
entries pin an explicit generous value.

| Yoke canonical event | Claude native | Codex native | Cursor native | Cursor CLI `-p` | Cursor IDE |
|---|---|---|---|---|---|
| `SessionStart` | `SessionStart` | `SessionStart` (matcher `startup\|resume`) | `sessionStart` | fired | fired |
| `SessionEnd` | `SessionEnd` | *(not wired)* | `sessionEnd` (`reason`, `final_status`, `duration_ms`) | fired | not fired while chat stays open |
| `UserPromptSubmit` | `UserPromptSubmit` | `UserPromptSubmit` | `beforeSubmitPrompt` (`prompt`, `attachments` incl. applied rule files) | **absent** | fired |
| `PreToolUse` | `PreToolUse` × matcher | `PreToolUse` (+ `PermissionRequest` collapse) | `preToolUse` (`tool_name`, `tool_input`, `tool_use_id`); shell also gets dedicated `beforeShellExecution` (`command`, `sandbox`) | fired | fired |
| `PostToolUse` | `PostToolUse` | `PostToolUse` | `postToolUse` (+ `afterShellExecution` with `output`) | fired | fired |
| `PostToolUseFailure` | `PostToolUseFailure` | *(reconstructed from transcripts)* | `postToolUseFailure` (`failure_type`, `error_message`) | fired | fired |
| `Stop` | `Stop` | `Stop` (stdout must be `{}`) | `stop` (token counts, `loop_count`, `status`) | **absent** | fired |
| Subagent lifecycle | `SubagentStop` (rendered into subagent adapters) | in-process, same session | `subagentStart` / `subagentStop` (`subagent_type`, `subagent_id`, `parent_conversation_id`) | **absent** (despite four `Task` dispatches) | fired |

Cursor-only events with no Yoke chain today: `beforeReadFile` (payload
carries file content — a read-gate Yoke has never had), `afterFileEdit`
(full `edits[{old_string,new_string}]` diff), `afterAgentResponse`,
`beforeMCPExecution` / `afterMCPExecution`, `preCompact`, Tab events. The
non-interactive CLI omits exactly the conversational-loop events (no typed
prompt, no waiting turn boundary), so a Cursor manifest must declare
per-surface affordances, not one list.

`afterAgentThought` is not wired, and nothing else needs to be. It fires
inside the token stream — 17 times during one two-token reply — with the
stream held open across the hook, so the hook is charged against the
generation connection and failures surface as `RetriableError:
WritableIterable is closed`, naming nothing hook-shaped. Deny-capability is
not the mechanism: `beforeShellExecution` and `beforeReadFile` are
deny-capable and run the full command safely, because they fire between
operations. Measured on 2026.07.23, six `cursor-agent -p` runs each:

| hook on `afterAgentThought` | duration | clean runs |
|---|---|---|
| none | — | 6/6 |
| `echo {}` | 0.04s | 4/4 |
| `sleep 0.25; echo {}`, no Yoke code | 0.25s | 2/6 |
| `yoke hook evaluate`, work detached after replying | ~0.3s | 3/6 |
| `yoke hook evaluate`, synchronous | ~0.7s | 2/6 |

On 2026.08.25 the shell-cost row is gone: `cat > /dev/null; exit 0`,
`printf "{}"`, and `echo {}` each broke the stream, one break per thought,
until the reconnects ran out. The budget this event once had is now zero,
whatever the hook replies — bisect in
[the decision record](archive/decisions/woken-turn-survives-to-take-delivery.md).

Losing it costs nothing, because the same build moved the answer it
carried. It was the only event naming a concrete model while every other
payload reported the `"default"` placeholder, and nothing else recovered
one: transcripts record only `{role, message}`, hook processes are children
of `/bin/zsh -lc` not `cursor-agent`, and no model env var is exported. Now
`sessionStart`/`sessionEnd` and the tool-call events name a bare `model`
(`grok-4.6`) with no `model_id` and no effort tier. Registration prefers
`model` over `model_id` when both exist; a launch-bound cursor session
then stores the launch's `requested_model` in that same field. Owner:
`yoke_harness.hooks.identity_runtime.cursor_payload_model`.

**The one channel a resumed print-mode turn can be reached on is
`sessionStart`.** A stopped session is woken with `cursor-agent --resume
… --print`, and that mode fires only `sessionStart` and `sessionEnd` — no
`beforeSubmitPrompt`, no `stop`. A pending envelope therefore has exactly
one chance to reach the model before its first tool call, which is why the
delivery modules must put it in the `additional_context` reply rather than
beside it on raw stdout (see `yoke_contracts.hook_runner.model_context_channel`).

### Decision wire format and context injection

| Concern | Claude Code | Codex | Cursor |
|---|---|---|---|
| Deny | exit 2 + stderr/stdout narrative | exit 0 + `hookSpecificOutput.permissionDecision: "deny"` | exit 0 + `{"permission": "deny"}` (also `"allow"` / `"ask"`); exit 2 equivalent |
| Denial narrative to model | stdout text | JSON field | `agent_message` (model) + `user_message` (operator) |
| Allow-time advisory | `hookSpecificOutput.additionalContext` | same | `postToolUse.additional_context`; no allow-time channel on `preToolUse` — advisory-only chain output needs rerouting or omission via `AdapterCapability.pretool_omissions` |
| Rewrite tool input | — | — | `preToolUse.updated_input` |
| Orientation injection | `UserPromptSubmit` additionalContext | `SessionStart` | `sessionStart.additional_context` (measured working; only channel in `-p` mode, where `beforeSubmitPrompt` never fires) |
| Stop discipline | empty allow; hold is `{"decision":"block","reason":...}` | allow `{}` from session dispatch, short-circuit on `stop_hook_active`; hold is `{"decision":"block","reason":...}` | allow-path `{}`; hold uses `followup_message` for same-session self-continuation only; stop/sessionEnd commands peel a missing `.worktrees/<lane>` `YOKE_ROOT` and a `~/.cursor/hooks.json` backstop covers deleted project cwd |

## Session identity, process shape, container model

| Concern | Claude Code | Codex | Cursor (measured) |
|---|---|---|---|
| Session id source | `CLAUDE_CODE_SESSION_ID` env; persisted to `$CLAUDE_ENV_FILE` | `CODEX_SESSION_ID` (parent thread, exported into subagents too; `CODEX_THREAD_ID` is the running thread. Both absent in hook subprocesses → identity env pin in hook command) | **No env var.** Every payload carries `session_id` + `conversation_id` (identical values), plus `generation_id` per turn and `tool_use_id` per call |
| Executor detection | process/env heuristics | `YOKE_EXECUTOR=codex YOKE_PROVIDER=openai` pinned in hook command | same pin approach works; `CURSOR_INVOKED_AS=cursor-agent` distinguishes CLI from IDE (unset), `CURSOR_VERSION` carries build |
| Process ancestry | anchorable (`claude` basenames) | multiplexed (never an anchor) | **multiplexed** — one `cursor-agent` pid hosted five session ids; hooks run `python3 → zsh → cursor-agent` |
| Ambient identity for agent-shell subprocesses | env chain + process anchors | anchors unusable; env pin | `CURSOR_PROJECT_DIR`, `CURSOR_TRANSCRIPT_PATH`, `CURSOR_USER_EMAIL` exported to hook processes; the agent shell gets `CURSOR_CONVERSATION_ID` (its own conversation, a subagent's for a subagent shell) but no session id. Anchors are unusable for the same reason as Codex, so identity rides the hook-written conversation mapping (`<machine-home>/cursor-session-map/`, `yoke_contracts.cursor_session_map`) |
| Container correlation | n/a (subagents share session) | n/a (in-process) | Subagents get **their own `session_id`** and transcript. Two recovery channels: `subagentStart`/`subagentStop` payloads carry `parent_conversation_id`; every hook process env (`CURSOR_TRANSCRIPT_PATH`) points at the **top-level** session transcript, including inside subagent hooks (unset for a session's first events — take the id from `sessionStart`'s payload, use the env var thereafter) |

Yoke's model treats the top-level session as the container for main-agent and
subagent work. The adapter must therefore register only the top-level
`session_id` as a `harness_sessions` row and fold sub-session hook events
into that container via the channels above — the ensure-register reflex that
treats any unknown session id as registrable would otherwise mint phantom
sessions per subagent dispatch. Subagent tool calls **do** fire
`preToolUse`/`postToolUse` under the sub-session id (measured: 7/7/4 events
in one dispatch), which is both how lint enforcement reaches inside a
subagent and how the conversation mapping learns that sub-session id: those
events fire on the non-interactive terminal surface, where `subagentStart` /
`subagentStop` never do.

### Session lifecycle

- **Orientation**: Claude delivers on `UserPromptSubmit`, Codex on
  `SessionStart`. Cursor: `sessionStart` is the universal channel; the IDE
  additionally offers `beforeSubmitPrompt` context (attachments show which
  rule files applied).
- **End-of-session**: the CLI fires `sessionEnd` reliably at process exit;
  the IDE did not fire it while the chat stayed open, and its
  transient-signal behavior (sleep, reload, window close — `reason` enum
  includes `window_close`) is unmeasured. Route through the same
  non-destructive `end_session_if_empty` path as Claude's transient-end
  defense; never assert "agent gone" from `sessionEnd` alone.
- **Stale TTL**: fleet machinery now ends Codex and Cursor sessions at every
  stop, so one `session_stale_ttl_minutes` base applies on every harness.
  Sessions with active holdings use `session_stale_ttl_with_holdings_minutes`.

## Tool surface mapping

| Yoke chain matcher | Claude tool | Codex tool | Cursor tool (measured) |
|---|---|---|---|
| `Bash` | `Bash` | `Bash` | `Shell` (plus dedicated `beforeShellExecution`, the richer gate: raw `command` + `sandbox` state) |
| `Edit` / `Write` | `Edit`, `Write` | `apply_patch` | `Write` (gate at `preToolUse`; `afterFileEdit` supplies the post-hoc diff) |
| `Read` | `Read` | — | `Read` (plus `beforeReadFile`) |
| Subagent dispatch | `Agent` | custom-agent spawn | `Task` — `tool_input.subagent_type` names the target, so dispatch is gateable at `preToolUse` even where lifecycle events are absent |
| `Monitor` / `ScheduleWakeup` / `TaskOutput` | Claude-only wake primitives | n/a (PTY streaming) | **no equivalent observed** — Codex-tier foreground watcher wrappers apply |

Also observed: `Grep` as a distinct tool name. MCP tools surface as
`MCP: <server>` matcher forms with their own before/after events.

## Rendering, subagents, skills

| Concern | Claude Code | Codex | Cursor |
|---|---|---|---|
| Adapter format | `runtime/harness/claude/agents/yoke-*.md`, YAML frontmatter (`tools`, `disallowedTools`, `model`, `maxTurns`, `permissionMode`, `hooks`) | `runtime/harness/codex/agents/yoke-*.toml` (`developer_instructions`, optional pinned `model`, `sandbox_mode`) | `.cursor/agents/*.md`, frontmatter `name` + `description` (vendor docs add `model`, `readonly`, `is_background`) |
| Per-tool restriction | `tools` allowlist enforces PM/PD non-Bash | `sandbox_mode` posture | **none** — no `tools` field. Mitigate with hook policy: deny `Shell` at `preToolUse` inside sessions whose container mapping says the active subagent is a non-Bash role, or deny at `subagentStart` |
| Subagent hook wiring | per-agent `hooks` frontmatter composed by `agents_render_subagent_hooks` (`YOKE_HOOK_AGENT_TYPE=<role>` env wrap) | none (in-process) | hooks are global; role identity must come from `subagentStart.subagent_type` + sub-session mapping rather than per-agent env wraps — `lint_subagent_background`'s context detection needs this channel |
| Compat consumption | — | native `.agents/skills` scan | reads `.claude/agents/` directly (measured; Claude-only frontmatter keys tolerated). Viable interim `canonical_agents.consumption` posture; a rendered `.cursor/agents/` pass is the clean end state |
| Skills | `.claude/skills/yoke` symlink | native `.agents/skills` scan | **native `.agents/skills` scan (measured)** — probe skill discovered and loaded; no mirror needed in the source repo |
| Conditional prose | `<!-- YOKE:HARNESS claude -->` fences Monitor/background primitives | elided | elision is correct for the wake primitives (absent in Cursor), but every fenced block needs an audit: a Cursor render inherits *neither* branch by default |

## Install surface and operational hazards

- Repo/root artifacts a Cursor adapter adds: `runtime/harness/cursor/`
  (manifest, hooks.json, adapter, agents, smoke-test runbook), a
  materialized `.cursor/hooks.json` copy kept byte-identical to the canonical
  runtime file (Cursor rejects symlinked project hook configs), a root
  `CURSOR.md` shell doc, entries in the
  project-install hook-key/merge-target/bundle-validation constants and
  `INSTALL_BUNDLE_SOURCE_DIRS`, and managed-install links for
  `.cursor/skills` parity decisions.
- `.cursor/cli.json` schema is strict: `permissions.allow` is **required**
  (an allow-less deny-only file aborts every run before the agent starts) —
  the same all-or-nothing failure class as Claude's `settings.json`.
  `HC-cursor-permission-config` covers it, alongside the
  `.cursor/sandbox.json` `networkPolicy` allow list that keeps sandboxed
  `yoke` calls from failing against the control plane. Both regions are
  merged in by the install pass rather than shipped as literal bundle files,
  so operator entries survive; the network origins resolve from machine
  config at install time because a server-built bundle cannot know which
  control plane the installing machine talks to.
- Approval/execution mode is machine-level and unreachable from a project
  repo, so it is taught rather than installed (`CURSOR.md`) and reported by
  `HC-cursor-approval-posture`. An explicit `full_network` request counts as
  an escalation and prompts even for allowed hosts — the correct move once
  the origins are allowed is to retry inside the sandbox.
- Interactive `cursor-agent` gates on a Workspace Trust dialog; `--trust`
  clears it for automation. Non-interactive `-p` runs did not prompt.
- `cursor agent <anything>` from the IDE's bundled launcher silently
  downloads and installs the `cursor-agent` binary when absent — onboarding
  docs should install it deliberately, not as a side effect.
- CLI permission layers stack independently of hooks (`Shell(cmd)` /
  `Read(glob)` / `Write(glob)` allow/deny in `~/.cursor/cli-config.json` +
  project `.cursor/cli.json`), giving two gating layers where Claude has one.
- `cursor-agent` has native worktree flags (`-w`, `--worktree-base`); Yoke
  owns worktree placement, so adapters should leave these unused.

## Registry, offer, board, doctor

- `HARNESS_UNIVERSE` + per-command `harness_support` drive
  `supported_paths`; the manifest declares limitations only. Cursor's
  print-mode gaps (no `beforeSubmitPrompt`/`stop`) belong in
  per-surface affordance declarations, not disabled paths.
- The session offer requires a canonical session id for recognized harnesses
  (`service_client_sessions_offer`); Cursor must join that gate or it
  silently takes the fallback-id path.
- Board/labels: new `EXECUTOR_EMOJI` entry (glyph must satisfy
  `HC-board-emoji-universality`), surface labels for IDE vs CLI
  (`CURSOR_INVOKED_AS` is the discriminator), and a
  charge-frontier `executor_default_lane_<token>` decision.
- Doctor updates: `HC-executor-canonicalization` (hardcoded `claude-%` /
  `codex-%` patterns), `HC-session-identity-provenance` label roster,
  `HC-harness-substrate-drift` render coverage, `HC-install-bundle-drift`.
  New checks clone the Codex pattern: hook-matcher completeness and
  hook-floor version gate (per `check_codex_hooks.py`), adapter drift and
  subagent surface truth (per `check_codex_agent.py`), plus a deny smoke.
  `runtime/harness/test_hook_runner_parity.py` needs the third
  `AdapterCapability` in its chain-equality matrix.

## Landing tiers

1. **Wrapper-only** (correctness without hooks, per the adapter template):
   manifest + vocabulary/enumeration edits + identity predicates (both
   copies) + process-ancestry classification + session-offer gate +
   `CURSOR.md` + doctor roster updates. Yields truthful registration,
   routing, and board presence.
2. **Hook-enhanced**: `.cursor/hooks.json` renderer, Cursor
   `AdapterCapability` (stdin payload parser, `Shell→Bash` matcher mapping,
   decision renderer, advisory omissions), session-dispatch branches
   (orientation via `sessionStart`, non-destructive end handling), container
   mapping for sub-session events, hook-floor HC + deny smoke, parity-test
   entry.
3. **Subagents and render**: consumption-mode decision (`.claude/agents`
   compat vs rendered `.cursor/agents`), role-aware subagent policy over
   `subagentStart`/`Task`, conditional-block audit, managed project-install
   layer.

## Launched-worker turn semantics and binding (measured 2026-08-26)

Six consecutive `cursor-cli` launch failures over two days, against a
`cursor-agent` probing healthy at `2026.08.25-3e8eec8`, resolved into three
facts — read from control-plane rows, not inferred.

**A launch never creates a Cursor session with `-p`.** `cursor-agent -p` runs
one print-mode turn against a session that already exists and exits, owning
and registering nothing — hence `CursorCliTransport` is resume-only and
launches go through ACP (`session/new` + `session/prompt`). A launched worker
is therefore not "one response and done": the ACP session keeps taking turns
while the agent works, and needs no continuation nudge. What bounds the relay's
attention is `CURSOR_ACP_TURN_SECONDS`, after which its drain thread stops
following the prompt; measured natives worked for minutes past that (79 and 71
tool calls over 9 and 6 minutes), so the drain is not what ends a worker.

**A Cursor cold start regularly outlives the relay's registration proof.**
`complete_bound_launch` waited `CURSOR_REGISTRATION_WAIT_SECONDS`, a
prompt-mode registration turn, then `CURSOR_REGISTRATION_TURN_WAIT_SECONDS`
for the conversation map to prove hooks had fired. Launch `e058a2e9` gave up
at 54s with `registration_unproven` and reaped the native; session `9d8017c0`
registered ten seconds later and ran 43 tool calls with its launch already
closed. A map miss is now a created native with
`native_launch_phase=registration_pending`: the registration deadline decides
the outcome, and the supervision record still reaps a native that never
registers.

**Model labels are two vocabularies, and equality between them refused every
correctly-bound launch.** A launch requests the string `cursor-agent --model`
accepts (the machine-config preferred model, e.g `cursor-grok-4.6-high-fast`);
a Cursor session registers the concrete model its own hook payload names
(e.g `grok-4.6`). The launch binding compared the two for
equality, so launches `e2b0473e` and `8e88bd1f` — natives that registered
under exactly the `native_session_id` the relay recorded and ran 71 and 79
tool calls — were refused `model_mismatch` on every attestation retry, never
received their instruction, surveyed unassigned, and were reaped claim-free
while their launch rows read `late_registration`. The native session id proves
exact identity already, so the binding records `requested_model` /
`registered_model` as evidence instead of refusing.

## Open questions

- IDE `sessionEnd` semantics on window close, reload, and machine sleep —
  does Cursor exhibit Claude's transient-signal class?
- Session id stability across `--resume` / `--continue` and IDE chat
  reopening (episode model).
- Print-mode subagent lifecycle: `Task` dispatch fires no
  `subagentStart`/`subagentStop` in `-p` mode — vendor gap or intended?
- Whether the conversation map can land early enough to be launch
  registration proof again, rather than the optimistic fast path it now is.
- Minimum Cursor version for the hook surface (the manifest's
  `hook_enhanced` floor) — the measured builds are single data points.
- `beforeShellExecution` vs `preToolUse(Shell)`: run the Bash chain on one,
  both, or split gate/advisory roles between them?
- Whether `updated_input` rewriting and `beforeReadFile` gating open
  enforcement options Yoke has no chain vocabulary for yet.
- MCP and `preCompact` events (unexercised), and `Write`-tool coverage of
  every edit path the IDE offers (only agent-driven edits were measured).
