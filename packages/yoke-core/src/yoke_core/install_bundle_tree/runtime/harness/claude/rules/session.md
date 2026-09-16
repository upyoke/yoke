# Claude — Session Rules

This file holds only Claude-Code-specific session rules, in their **normative short form**. **For every harness-neutral rule — worktree discipline, commit discipline, bug discipline, deployment rules, lifecycle, simplify, DB access — read `AGENTS.md` at your repo root.** If a rule belongs in Codex sessions too, it lives in AGENTS.md, not here.

The reasoning, recovery paths, watcher inventory, and worked failure modes behind everything below are in [`.yoke/docs/reference/agent-rules/claude-sessions.md`](.yoke/docs/reference/agent-rules/claude-sessions.md). Read the relevant part **before** the action it governs. That split exists because this file is delivered through a finite startup channel; what sat past the cut was in force and unread.

Paths here are repo-root-relative, because this file is read from `.claude/rules/` in an installed project and from `runtime/harness/claude/rules/` in the Yoke source tree.

What stays Claude-specific depends on a primitive Codex lacks: the `Monitor` wake-as-turn primitive, the `PreToolUse`/`PostToolUse` hook surface, the Claude `settings.json` schema, and the `AskUserQuestion` tool name.

When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.

## Hook Schema (Claude-only)
- **Hook schema is all-or-nothing.** One invalid entry in `settings.json` silently disables ALL hooks. Every entry — `UserPromptSubmit`, `SessionEnd`, all of them — must use the nested `{hooks: [{type, command}]}` shape; the flat `{type, command}` form breaks the whole file. If hooks seem dead, check `claude` CLI startup for "Settings Error".

## SessionEnd and Session Identity (Claude-only)
- **Claude fires `SessionEnd` on transient signals** — laptop sleep, app reload, brief disconnect, idle timeout — not only on permanent termination. So the Stop and SessionEnd hooks never assert "agent gone" on their own: they end a session only when it holds nothing at all, and report a structured skip reason otherwise. They never release claims.
- **A pure wake target holds no claim by design.** A caller that needs one alive takes a bounded lease: `yoke sessions keepalive hold <session-id> --reason ... [--seconds N]`, cleared by `yoke sessions keepalive release` or expiry. That lease is control-plane state; the held session's own tool calls neither set nor clear it. `parked` mode is the opposite — a session declares it about itself and its next tool call takes it back.
- **A transient end self-heals on the next hook event of any kind,** including `PreToolUse`/`PostToolUse`. Revival does not wait for `SessionStart` or `UserPromptSubmit`, because an agentic turn continuing past a sleep never submits a new prompt.
- **One `session_id` may legitimately span multiple episodes,** and that is intentional — the same conversation resumes under the same id. Locks attached to the prior episode remain valid; there is no per-episode handoff to coordinate.
- **Reactivation reacquires conditionally:** inside the reacquire window, with no other live holder, the claim is re-inserted in the same transaction. When another session legitimately holds the target, recovery is explicit: `yoke claims work acquire --item PREFIX-N --reason session-reactivation-recovery`.
- **A surface that refuses `SESSION_ENDED` names its recovery** — a populated `yoke sessions begin ...` built from the ended row's own stored identity. Follow the printed recipe rather than improvising.
- **Episode-scoped audit goes through `--current-episode`** on `yoke events query --session <id>`. It REQUIRES an explicit session and fails closed. **Read `elided_prior_episode_rows`:** an empty `rows` beside a non-zero count means "ask again without the flag", not "nothing happened". The portable, episode-blind claim-holder read is `yoke claims work holder-get PREFIX-N`; inherited claims stay visible there on purpose.

## Tool Constraints (Claude-only)
- `AskUserQuestion` requires at least 2 options. Per the shared Interaction Style rule in AGENTS.md, prefer inline chat; use it only for short, discrete choices.

## Long commands — tier router (read this first)
Two tiers with different authority. Apply only the one matching your session tier; **do not cross-apply.** If unsure, you are a subagent (subagents have `YOKE_HOOK_AGENT_TYPE` exported by their adapter; the main session does not).

**Main-session tier** (the top-level session running `/yoke` skills inline):
- **Invoke watcher-backed long commands with `--print-streaming-pair` first.** It prints and runs nothing — it launches no child, merges nothing, deploys nothing, records nothing — and reports the safe wait for this session's harness wake capability. Then run the printed command yourself; that run is the operation.
- `wait_mode=background-wake` → run the printed background command and its `yoke watch tail` subscription once. `wait_mode=in-turn` → run the printed foreground invocation and keep it open until it exits. Unknown always waits.
- **Give every `in-turn` watcher invocation `timeout: 600000` on the Bash tool.** At the 120-second default the harness moves the call to a background task, and a turn that ends there kills the watcher it was holding. Headless Claude watcher Bash omitting it is denied by `lint-headless-watcher-timeout` — not a blanket Bash rule.
- **A backgrounded call is still running — it was not interrupted.** Some commands outlive even 600000 (a CI-routed QA gate is 13-14 minutes). Reading the background task's output is how you continue the call, not how you end the turn; keep reading until it exits and you have its outcome. Re-run only once the process is verifiably gone.
- **Do not Stop after arming Monitor while you hold a work claim.** Monitor wakes resume the current turn; ending it closes the reader and the paired `watch_tail` dies on a broken pipe with no completion record and no later wake. The Stop promised-work gate holds such a Stop rather than allowing it. Expect the block, and expect it to cost you the turn — park first if you need the session quiet.

**Subagent tier** (any dispatch via the `Agent` tool):
- **Long commands run foreground inside a single `Bash` tool-call sequence** via `yoke watch pytest -- <args>` or a sibling wrapper. **Never `Bash(run_in_background: true)` + `Monitor` and then return:** the subagent turn is atomic, so any wake fired afterwards has nowhere to deliver — the subagent suspends mid-flight, the parent dispatch deadlocks, and watcher subprocesses leak around shared control-plane resources. `lint_subagent_background` denies backgrounding tools in subagent context (default `deny`).
- If the turn budget cannot fit the foreground run, the orchestrator fans out tighter dispatches. Growing the budget to fit a self-armed background pattern is not a workaround.

**Both tiers:**
- **Do not manually poll a running long command.** In `background-wake` the one armed subscription is the progress surface; in `in-turn` the original foreground call is the waiter. The minted `yoke watch tail <progress-capture>` is the only sanctioned Monitor shape — it exits on the completion sentinel, while bare `tail -f` on a watcher capture is denied. One post-completion `tail -80 <raw-capture>` is fine.
- **Prefer the wrappers over a hand-authored filter,** and confirm no wrapper covers the command before falling back: a command may be a *subcommand* of one (`yoke merge item` → `yoke watch merge merge-item`). The wrappers are `yoke watch pytest | merge | deploy | fleet | preflight | qa-case | doctor`; the inventory, filters, and exit statuses are in the deep home.
- **On Monitor wakes, relay the matched line into your own output.** That line IS the update the operator wants — emit it verbatim or as a tight one-line paraphrase preserving the concrete signal. Never substitute filler like "Still waiting." A `# watch_<kind> digest …` line is one wake covering everything in it: relay it whole, including any `(suppressed N ticks)` suffix.
- **Relay is your own visible output and nothing else.** It never authorizes mailing a watcher line to another session. A worker must not `yoke say` progress upward — a percentage, an elapsed poll, a "still green" note costs the recipient an inbox row and changes nothing it would do. Ending a turn sends no Fleet message; send terminal and actionable reports deliberately with `yoke say --steering`. Message another session only for something it would act on: a red gate and what failed, a blocker, a conflict with your instruction, a defect outside your scope, a terminal item state, or a decision you need.

**Suppression tokens** (add to the Bash command body; all are recorded in the audit event): `# lint:no-main-check` overrides the main-branch commit block; `# lint:no-lifecycle-mutation-check` the raw-lifecycle-mutation block; `# lint:no-polling-check` the polling guardrail. `# lint:no-monitor-watcher-tail-check` and `# lint:no-raw-pytest-check` are audit-only and do NOT unblock — use the minted `yoke watch tail` or `yoke watch pytest` instead.

## Harness wake capability
Wake capability is a manifest fact, not prose. Source of truth: `agent_wake` in `runtime/harness/<harness_id>/manifest.json`, rendered from `yoke_contracts.harness_wake_capability`. Change the contract and re-render; never restate one of these facts on a document's own authority. Cross-harness behavior you author must match what each harness declares, not what this Claude-only file makes convenient.

## Cross-references
- **Path-claim overlaps surfaced mid-flow:** the resolution protocol is `.agents/skills/yoke/idea/path-claim-blocking.md`.
- **Agent-to-Yoke surface boundary:** the canonical shape is `yoke <subcommand>`. The HTTP function-call server, `curl localhost:8765`, `$YOKE_API`, and direct runtime-API imports are not agent shapes; `lint-no-agent-runtime-api-import-from-c` and `lint-no-agent-curl-against-yoke-api` enforce it in both main-session and subagent contexts. Full stance: AGENTS.md `### yoke CLI`.
