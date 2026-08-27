# Hook Parity Map

*Three-tier classification of Yoke's hook surface by harness availability. This document defines which hooks exist, what Yoke behavior they provide, and which harnesses can use them.*

## Overview

Yoke's hook infrastructure provides startup orientation, Bash tool guardrails, post-tool telemetry, and agent lifecycle safety nets. Not all harnesses support the same hook events. This map classifies every hook by its availability tier and documents the Yoke behavior coverage for each.

The tested Codex hook events (`SessionStart`, `UserPromptSubmit`, `PreToolUse` Bash/apply_patch matchers, `PostToolUse` Bash/apply_patch matchers, and `Stop`) are the basis for the cross-harness parity slice. `PostToolUseFailure` is not part of the Codex hook surface. Bash failure classification on Codex is handled inside the `PostToolUse` path, not by a separate event. Hooks outside this tested set remain Claude-Code-only until verified in additional harnesses.

## Three-Tier Classification

### Universal (no hook dependency)

Behaviors in this tier work in any harness, including wrapper-only mode with zero hook support. They rely on Yoke core paths, explicit entry commands, or harness-native configuration -- never on hooks.

| Behavior | Mechanism | Harness requirement |
|----------|-----------|---------------------|
| Bootstrap orientation (startup reads) | `python3 -m yoke_core.hooks.bootstrap render-full` or harness-native config | Bash tool only |
| Session identity declaration | Environment variables (`YOKE_EXECUTOR`, `YOKE_PROVIDER`, `YOKE_MODEL`) | Bash tool only |
| Canonical telemetry (`HarnessSessionOffered`, `NextActionChosen`) | Yoke core session-offer path (`packages/yoke-core/src/yoke_core/domain/sessions.py`) | None (core-owned) |
| Route wrapper (command invocation) | Entry launcher delegates to `/yoke` operator commands | Bash tool only |
| Routing and fallback decisions | `/yoke do` session-offer evaluation | None (core-owned) |

### Cross-harness (tested hook subset)

Behaviors in this tier use hooks that have been verified in both Claude Code and Codex (>= 0.128.0-alpha.1). They provide optional enhancements over the Tier 1 baseline. Correctness never depends on them.

| Hook event | Yoke behavior | Claude Code | Codex (tested) |
|------------|----------------|-------------|-----------------|
| `SessionStart` | Register session in harness_sessions with authoritative model from payload (emits `HarnessSessionStarted`) | Via `yoke hook evaluate SessionStart` | Via `.codex/hooks.json` + bounded non-login `/bin/sh` wrapper around `env YOKE_EXECUTOR=codex YOKE_PROVIDER=openai yoke hook evaluate SessionStart` |
| `UserPromptSubmit` | First-prompt orientation injection (emits `HarnessSessionSentFirstUserPromptSubmit`); idempotent re-registration safety net | `yoke hook evaluate UserPromptSubmit` | Via `.codex/hooks.json` + bounded non-login `/bin/sh` wrapper around `env YOKE_EXECUTOR=codex YOKE_PROVIDER=openai yoke hook evaluate UserPromptSubmit` |
| `PreToolUse` (Bash matcher) | Python-owned lint guardrails and command validation. The Codex adapter derives the Bash chain from `yoke_contracts.hook_runner.hook_ordering.ordered_pipeline_for("PreToolUse", "Bash")` — including `lint_long_command_polling` for polling discipline and `lint_pipe_to_truncator` for the live-long-command pipe-to-truncator clause. The shared `yoke_core.hooks` runner enforces parity behind the CLI. | `.claude/settings.json` hook commands | Via `.codex/hooks.json` + bounded non-login `/bin/sh` wrapper around `env YOKE_EXECUTOR=codex YOKE_PROVIDER=openai yoke hook evaluate PreToolUse` |
| `PreToolUse` (`apply_patch` matcher) | Python-owned write-side path and lifecycle guardrails on Codex's file-edit tool | Equivalent on Write/Edit matchers | Via `.codex/hooks.json` + bounded non-login `/bin/sh` wrapper around `env YOKE_EXECUTOR=codex YOKE_PROVIDER=openai yoke hook evaluate PreToolUse` |
| `PostToolUse` (Bash matcher) | Python-owned telemetry, DB-query failure detection, and Bash failure classification. Claude Code delivers explicit failures via `PostToolUseFailure`; Codex does not — see below for how Codex failure telemetry is recovered inside the `PostToolUse` handler. | `.claude/settings.json` hook commands | Via `.codex/hooks.json` + bounded non-login `/bin/sh` wrapper around `env YOKE_EXECUTOR=codex YOKE_PROVIDER=openai yoke hook evaluate PostToolUse` |
| `PostToolUseFailure` (Bash matcher) | Python-owned telemetry for Bash tool failures — `HarnessToolCallFailed` classification with nonzero exit semantics. | `.claude/settings.json` hook commands | **Not supported by Codex.** OpenAI's hooks docs do not list this event; live Codex sessions confirm it never fires. Codex Bash failure telemetry is recovered inside the `PostToolUse` handler via (1) `Exit code N` parsing of `tool_response` content, (2) a hard-failure text fallback for `No such file or directory` / `command not found` / `Permission denied`, and (3) last-resort transcript reconciliation against `transcript_path` — matching `tool_use_id` to the rollout's `call_id` to recover silent nonzero exits like `false` or `exit 7`. |

**Runtime floor:** Codex hook-enhanced mode requires Codex >= 0.128.0-alpha.1 with hook support. The proven Desktop setup is the repo-local hook pack in `.codex/hooks.json` plus a clean app relaunch. When the runtime floor is not met, the adapter falls back to wrapper-only mode (Tier 1) silently.

**Cross-harness hook dispatch:** the per-event command lines in the rendered manifests (`runtime/harness/claude/settings.json`, `runtime/harness/codex/hooks.json`) collapse to a single `yoke hook evaluate <event>` invocation per `(event, matcher)` pair — for example, `yoke hook evaluate PreToolUse` and `yoke hook evaluate UserPromptSubmit`. The CLI currently delegates to the local `yoke_core.hooks` implementation, which walks the universal ordering chain inside the process; the manifest no longer enumerates per-lint module command lines or injects a repo-root `PYTHONPATH`.

**Hook shell startup is deterministic:** generated Claude, Codex, and Cursor commands use non-login `/bin/sh` and prepend the configured XDG launcher directory, `~/.local/bin`, Homebrew, and system binary directories. Hooks therefore resolve `yoke` from a minimal GUI environment without reading operator shell startup files, which may contain interactive or blocking work that is unsafe inside a native hook.

**Codex identity pin:** the Codex hooks.json command shape pins `YOKE_EXECUTOR=codex` and `YOKE_PROVIDER=openai` before `yoke hook evaluate` so the hook subprocess attributes correctly even when the parent launcher does not export `CODEX_THREAD_ID`. Without the pin, `yoke_core.hooks.helpers_identity.detect_executor` falls back to the Claude family and stores `executor=claude-code` / `provider=anthropic` on the Codex Desktop session row plus `context.executor=claude` on every `HookDispatchTelemetry` envelope. The pin is owned by `packages/yoke-core/src/yoke_core/domain/agents_render_hooks.py` (`_CODEX_IDENTITY_ENV`) so any future Codex command-shape change keeps the executor/provider signal attached at one place.

**Codex hook trust is path-keyed, so worktrees need it mirrored.** Every Tier 2 Codex behavior above is conditional on the operator having trusted the hooks file: Codex records trust in `$CODEX_HOME/config.toml` as `[hooks.state."<hooks file>:<event>:<group>:<hook>"]` entries carrying a `trusted_hash`, and an untrusted hook does not run — the only override is Codex's own `--dangerously-bypass-hook-trust`. The key holds the *literal* path Codex loaded, with no symlink resolution, which is why a checkout's tracked `.codex/hooks.json` symlink is keyed at the symlink's own path. A linked git worktree materializes that same symlink at a different absolute path and therefore inherits none of the checkout's trust, so without intervention a Codex thread working in a worktree fires no hooks at all — no session registration, no telemetry, no guardrails, and the silence is indistinguishable from a quiet session. Worktree preparation closes this: `yoke_core.domain.worktree_codex_hook_trust` mirrors the checkout's entries onto each lane's path, for reused lanes as much as new ones. Trust is mirrored, never minted — an entry is written only when the lane's hooks file is byte-identical to the checkout's, and the value written is the hash the operator already granted to that exact content. Hook content that differs needs its own trust decision made in Codex. `HC-worktree-hook-trust` is the backstop for lanes that predate the mirroring step.

**Claude Code has no equivalent per-path hook gate.** Its per-project records in `~/.claude.json` carry a directory-level `hasTrustDialogAccepted` flag and no per-hook hash store, so hooks from a project's `.claude/settings.json` fire once the directory is trusted. A Claude session rooted at a worktree would prompt the one-time directory trust dialog and then run its hooks normally; there is no silent hash-keyed dead zone to mirror around.

### Cursor coverage

Cursor's hook surface is a near-superset of the tested cross-harness tier, with camelCase native event names mapped to canonical verbs in the rendered `runtime/harness/cursor/hooks.json` (surfaced as `.cursor/hooks.json`). Measured facts (Cursor IDE 3.14.7 / cursor-agent 2026.07.23; full matrix in [Cursor Harness Integration Assessment](harness-cursor-assessment.md)):

- The Bash chain anchors on `beforeShellExecution` (raw command + sandbox state), not a `preToolUse` Shell matcher — wiring both would run the chain twice per command. A hook deny holds even under the terminal agent's force mode, and `postToolUseFailure` fires with `failure_type=permission_denied` — an explicit failure event Codex lacks.
- Context injection is event-scoped: `sessionStart` and `postToolUse` accept `additional_context`; `preToolUse` has no allow-time channel, so the Cursor adapter's `pretool_omissions` elides advisory-only hint modules instead of silently dropping their output.
- Coverage differs per surface: the IDE fires the full set; the non-interactive terminal agent (`cursor-agent -p`) omits `beforeSubmitPrompt`, `stop`, and the subagent lifecycle events, so orientation rides `sessionStart` (both surfaces) rather than prompt-submit.
- Identity pin: the rendered command pins `YOKE_EXECUTOR=cursor` (provider stays payload-derived — Cursor multiplexes model vendors in one session). Subagents run under their own session ids; the payload parser folds them into the top-level container session, so telemetry and registration never mint per-subagent sessions.
- Model identity used to arrive late, on one event only, and that event cannot afford a hook. On cursor-agent 2026.07.23 every terminal-agent payload reported the literal `"default"` except `afterAgentThought`, which names `model_id` plus a variant-qualified `model` — and it fires inside the token stream with the stream held open across the hook. On 2026.08.25 both halves moved: `sessionStart` and `sessionEnd` now name the real model, and the streaming event tolerates **no** hook at all — `exit 0`, `printf "{}"`, and `echo {}` each break the stream once per thought until the reconnects run out and the run dies as `RetriableError: WritableIterable is closed`. So nothing is wired there, and registration reads the model from the payload that opens the session (`yoke_harness.hooks.identity_runtime.cursor_payload_model`). This was never a deny-capability limit: `beforeShellExecution` and `beforeReadFile` are deny-capable and run the full command safely because they fire between operations. Full measurements in [Cursor Harness Integration Assessment](harness-cursor-assessment.md).

### Claude-Code-only (no cross-harness equivalent)

Behaviors in this tier use hook events or matchers that have no tested equivalent in Codex or other harnesses. They remain Claude-Code-exclusive until a cross-harness equivalent is verified.

| Hook event | Yoke behavior | Why no cross-harness equivalent |
|------------|----------------|---------------------------------|
| `PreToolUse` (Write matcher) | Write-side path and label guardrails on Claude's `Write` tool | Codex's equivalent file-edit surface is `apply_patch`, covered as Tier 2 above; the Claude Write/Edit matchers stay Claude-specific |
| `PreToolUse` (Edit matcher) | Write-side guardrails via the Claude `Edit` tool | Same — covered cross-harness through Codex's `apply_patch` matcher in Tier 2 |
| `PostToolUse` (Write/Edit/Read) | Python-owned telemetry on non-Bash tools | Codex `PostToolUse` is only tested with the Bash matcher; non-Bash tool telemetry remains Claude-only |
| `PostToolUseFailure` (any matcher) | Python-owned telemetry for tool failures routed through a distinct event | Not a Codex hook event — OpenAI's hooks docs only document `SessionStart`, `PreToolUse`, `PostToolUse`, `UserPromptSubmit`, `Stop`. Codex Bash failures are recovered inside `PostToolUse` via text parsing + transcript reconciliation; non-Bash tool failures on Codex remain unrecovered for now. |
| `PreToolUse` (Monitor matcher) | Python-owned Monitor guardrails: (1) `lint_monitor_watcher_tail` denies a bare `tail -f`/`tail -F` first arm on a watcher capture and prints the sentinel-aware `yoke watch tail` replacement; (2) `lint_long_command_polling.evaluate_duplicate_monitor` enforces one Monitor subscription per capture for the full session; (3) `hint_monitor_relay` injects the canonical relay-only reminder into `additionalContext`. Both denial suppressions are audit-only. | **Not a Codex event.** Codex has no Monitor primitive — long-running commands stream via native PTY output, so there is no `Monitor` tool to wake on per-match, no duplicate-Monitor failure mode, and no `tail -f`-style watcher arming to gate against. Codex callers run watcher wrappers (`watch_pytest`, `watch_merge`) as foreground commands and rely on PTY streaming; the floor-level rule from AGENTS.md's `## Command Output — Hard Rule` (capture-first, fallback cadence 60s -> 90s -> 120s -> max ~300s) is the complete Codex-side surface. |
| `PostToolUse` (Bash, Engineer-only) | Python-owned progress sync to GitHub | Agent-scoped hooks require subagent dispatch infrastructure |
| `Stop` | `yoke hook evaluate Stop` for both Claude Code and Codex. Codex pins `YOKE_EXECUTOR=codex YOKE_PROVIDER=openai` in the rendered command. Both routes run bounded `session-end-if-empty` through the CLI-backed local runner; Codex stdout stays `{}`. Claimless sessions end during the hook, while claimed or chain-pending sessions stay active for prompt reactivation / stale-session reclaim. | Codex Stop event not tested as a true archive/session-end equivalent |

## Tested Hook Coverage Summary

The following table summarizes the Codex hook events that actually fire in hook-enhanced Codex builds and are used by Yoke.

| Hook | Tested in Codex | Yoke behavior covered | Gap vs Claude Code |
|------|-----------------|------------------------|--------------------|
| `SessionStart` | Yes | Bootstrap injection | Claude Code uses `UserPromptSubmit` instead; functionally equivalent |
| `UserPromptSubmit` | Yes | First-prompt orientation | Equivalent coverage |
| `PreToolUse` (Bash) | Yes | Bash lint guardrails (5 lint scripts) | Write/Edit matchers not covered |
| `PostToolUse` (Bash) | Yes | Python-owned DB guardrails, tool telemetry, and Bash failure classification (see below — Codex lacks a `PostToolUseFailure` event, so failure recovery happens inside `PostToolUse`) | Write/Edit/Read telemetry not covered; Bash failure recovery depends on transcript reconciliation rather than a dedicated hook event |
| `PreToolUse` (`apply_patch`) | Yes | Python-owned write-side guardrails (path-claim coverage, lifecycle-mutation lint, write-path lint) on Codex's file-edit tool | None — this is Codex's structural equivalent to Claude's Write/Edit matchers |
| `PostToolUseFailure` | **Not a Codex event.** | — | Claude-only. Codex failure classification is handled via text parsing + transcript reconciliation inside the `PostToolUse` handler. |

### Codex Bash failure classification (three-layer recovery inside `PostToolUse`)

Because Codex does not emit a `PostToolUseFailure` event, Codex Bash failure telemetry must be recovered from the `PostToolUse` payload itself. The `observe.parse_hook_event` pipeline applies three layers in order:

1. **`Exit code N` parse.** When `tool_response` content carries a literal `Exit code 1` / `Exit code 2` / … string, `parse_hook_event` reads the number directly. Works for any runtime that mirrors the exit code into the response text (Claude Code, Codex's own stderr formatting for some commands).
2. **Hard-failure text fallback.** When the payload lacks both a top-level `error` and an `Exit code N` string but the response contains a stderr-shaped hard-failure indicator (`No such file or directory`, `command not found`, `Permission denied`) prefixed with a recognized command name, the record is reclassified as `HarnessToolCallFailed` with sentinel `exit_code=1`. Scoped to `hook_event == "PostToolUse"` so it only affects paths that would otherwise default to clean success.
3. **Transcript reconciliation (Codex follow-up to).** When the first two layers leave the record as `is_failure=False, exit_code in (None, 0)` and the payload carries a `transcript_path` plus `tool_use_id`, `_reconcile_codex_exit_code` reads the last 2 MB of the Codex rollout JSONL and looks for an `exec_command_end` entry whose `call_id` matches `tool_use_id`. If found, the entry's `exit_code` and `status` fields are authoritative. This is the only layer that catches silent nonzero exits like `false` or `exit 7`, which produce no output.

The transcript reader degrades gracefully on any I/O error, JSON decode failure, missing field, or schema mismatch — the hook path never crashes, and classification falls through to the unreconciled result. The Codex transcript JSONL schema (`payload.type == "exec_command_end"`, `payload.call_id`, `payload.exit_code`, `payload.status`) is not published by OpenAI on the public hooks docs page; it was derived from live rollouts under `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`.

Coverage tests live in `runtime/api/test_observe_codex_bash.py::TestCodexBashFailureTruth` (layers 1 and 2) and `runtime/api/test_observe_codex_transcript.py::TestCodexTranscriptReconciliation` (layer 3, including graceful-degradation assertions for missing files, schema mismatches, and the tail-bytes cap).

### What is not covered

- Non-Bash Codex tool failures (Write/Edit/Read/other). No hook-level parity with Claude Code's `PostToolUseFailure`; would require either native Codex field support or a per-tool reconciliation path.
- Historical event rows recorded before the transcript reconciliation landed — Yoke does not rewrite history, only fixes forward telemetry.
- Synthetic test telemetry in the canonical DB — tracked separately.

## Cross-Harness Coverage

The shared Yoke registry exposes two intentionally different capability views. The safe operator surface includes `/yoke conduct YOK-N` for direct Codex invocation. The narrower session-offer registry advertises entrypoints (`/yoke idea`, `/yoke do`, `/yoke refine`, `/yoke advance YOK-N implementation`, `/yoke polish`, `/yoke usher YOK-N [--dry-run]`) and downstream paths (`shepherd`, `refine`, `advance`, `dash`, `blitz`, `polish`, `usher`) used by `/yoke do` orientation and routing; Conduct is not a session-offer entrypoint or downstream path. [runtime/harness/codex/manifest.json](../runtime/harness/codex/manifest.json) declares Codex identity, affordances, and explicit limitations rather than copying either registry view. The full Tier 1 operator surface in [docs/harness-bootstrap.md](harness-bootstrap.md) §2 is part of Codex's safe surface unless the manifest declares an additional substrate limitation.

`/yoke conduct` is a current Codex-safe direct command. The shared dispatch descriptor module is the source for its agent lanes: phase files emit one task envelope per agent, and the substrate renderer ships the canonical agent body to both `runtime/harness/claude/agents/yoke-*.md` and `runtime/harness/codex/agents/yoke-*.toml` (surfaced at `.claude/agents/` and `.codex/agents/`). The `shepherd` path remains the quality-gated proof lane for PM, Designer, Boss, Architect, and Simulator work in both harnesses.

The remaining named substrate gap is the `PostToolUseFailure` event for non-Bash Codex tools; Bash failures are recovered through transcript reconciliation as documented above.

## Canonical Session-Offer Lineage

The canonical source of `HarnessSessionOffered` and `NextActionChosen` events is the shared core session-offer path in `packages/yoke-core/src/yoke_core/domain/sessions.py`. This path is harness-neutral -- both Claude Code CLI adapters and API callers emit the same events through the same code.

Harness-local hook output (e.g., Codex hook logs) is informational. It is never the canonical source for session lifecycle telemetry. This ensures that session-offer lineage is consistent regardless of which harness initiated the session.

## Related Docs

- [Harness Bootstrap Contract](harness-bootstrap.md) -- neutral startup expectations for all harnesses
- [Harness Adapter Template](harness-adapter-template.md) -- five-part adapter template with manifest schema
- [Session-Offer Contract](../.yoke/docs/reference/session-offer.md) -- request/response envelope and identity model
- [Harness README](../runtime/harness/README.md) -- adapter directory convention
