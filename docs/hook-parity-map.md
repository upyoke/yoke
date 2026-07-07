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
| Bootstrap orientation (startup reads) | `python3 -m runtime.harness.codex.codex_entry bootstrap` or harness-native config | Bash tool only |
| Session identity declaration | Environment variables (`YOKE_EXECUTOR`, `YOKE_PROVIDER`, `YOKE_MODEL`) | Bash tool only |
| Canonical telemetry (`HarnessSessionOffered`, `NextActionChosen`) | Yoke core session-offer path (`runtime/api/domain/sessions.py`) | None (core-owned) |
| Route wrapper (command invocation) | Entry launcher delegates to `/yoke` operator commands | Bash tool only |
| Routing and fallback decisions | `/yoke do` session-offer evaluation | None (core-owned) |

### Cross-harness (tested hook subset)

Behaviors in this tier use hooks that have been verified in both Claude Code and Codex (>= 0.118.0-alpha.2). They provide optional enhancements over the Tier 1 baseline. Correctness never depends on them.

| Hook event | Yoke behavior | Claude Code | Codex (tested) |
|------------|----------------|-------------|-----------------|
| `SessionStart` | Register session in harness_sessions with authoritative model from payload (emits `HarnessSessionStarted`) | Via `yoke hook evaluate SessionStart` | Via `.codex/hooks.json` + `/bin/zsh -lc 'env YOKE_EXECUTOR=codex YOKE_PROVIDER=openai yoke hook evaluate SessionStart'` |
| `UserPromptSubmit` | First-prompt orientation injection (emits `HarnessSessionSentFirstUserPromptSubmit`); idempotent re-registration safety net | `yoke hook evaluate UserPromptSubmit` | Via `.codex/hooks.json` + `/bin/zsh -lc 'env YOKE_EXECUTOR=codex YOKE_PROVIDER=openai yoke hook evaluate UserPromptSubmit'` |
| `PreToolUse` (Bash matcher) | Python-owned lint guardrails and command validation. The Codex adapter derives the Bash chain from `yoke_contracts.hook_runner.hook_ordering.ordered_pipeline_for("PreToolUse", "Bash")` — including `lint_long_command_polling` for polling discipline and `lint_pipe_to_truncator` for the live-long-command pipe-to-truncator clause. The shared `runtime.harness.hook_runner` runner enforces parity behind the CLI. | `.claude/settings.json` hook commands | Via `.codex/hooks.json` + `/bin/zsh -lc 'env YOKE_EXECUTOR=codex YOKE_PROVIDER=openai yoke hook evaluate PreToolUse'` |
| `PreToolUse` (`apply_patch` matcher) | Python-owned write-side guardrails (path-claim coverage, lifecycle-mutation lint, write-path lint) on Codex's file-edit tool | Equivalent on Write/Edit matchers | Via `.codex/hooks.json` + `/bin/zsh -lc 'env YOKE_EXECUTOR=codex YOKE_PROVIDER=openai yoke hook evaluate PreToolUse'` |
| `PostToolUse` (Bash matcher) | Python-owned telemetry, DB-query failure detection, and Bash failure classification. Claude Code delivers explicit failures via `PostToolUseFailure`; Codex does not — see below for how Codex failure telemetry is recovered inside the `PostToolUse` handler. | `.claude/settings.json` hook commands | Via `.codex/hooks.json` + `/bin/zsh -lc 'env YOKE_EXECUTOR=codex YOKE_PROVIDER=openai yoke hook evaluate PostToolUse'` |
| `PostToolUseFailure` (Bash matcher) | Python-owned telemetry for Bash tool failures — `HarnessToolCallFailed` classification with nonzero exit semantics. | `.claude/settings.json` hook commands | **Not supported by Codex.** OpenAI's hooks docs do not list this event; live Codex sessions confirm it never fires. Codex Bash failure telemetry is recovered inside the `PostToolUse` handler via (1) `Exit code N` parsing of `tool_response` content, (2) a hard-failure text fallback for `No such file or directory` / `command not found` / `Permission denied`, and (3) last-resort transcript reconciliation against `transcript_path` — matching `tool_use_id` to the rollout's `call_id` to recover silent nonzero exits like `false` or `exit 7`. |

**Runtime floor:** Codex hook-enhanced mode requires Codex >= 0.118.0-alpha.2 with hook support. The proven Desktop setup is the repo-local hook pack in `.codex/hooks.json` plus a clean app relaunch. When the runtime floor is not met, the adapter falls back to wrapper-only mode (Tier 1) silently.

**Cross-harness hook dispatch:** the per-event command lines in the rendered manifests (`runtime/harness/claude/settings.json`, `runtime/harness/codex/hooks.json`) collapse to a single `yoke hook evaluate <event>` invocation per `(event, matcher)` pair — for example, `yoke hook evaluate PreToolUse` and `yoke hook evaluate UserPromptSubmit`. The CLI currently delegates to the local `runtime.harness.hook_runner` implementation, which walks the universal ordering chain inside the process; the manifest no longer enumerates per-lint module command lines or injects a repo-root `PYTHONPATH`.

**Codex identity pin:** the Codex hooks.json command shape pins `YOKE_EXECUTOR=codex` and `YOKE_PROVIDER=openai` before `yoke hook evaluate` so the hook subprocess attributes correctly even when the parent launcher does not export `CODEX_THREAD_ID`. Without the pin, `runtime.harness.hook_helpers_identity.detect_executor` falls back to the Claude family and stores `executor=claude-code` / `provider=anthropic` on the Codex Desktop session row plus `context.executor=claude` on every `HookDispatchTelemetry` envelope. The pin is owned by `runtime/api/domain/agents_render_hooks.py` (`_CODEX_IDENTITY_ENV`) so any future Codex command-shape change keeps the executor/provider signal attached at one place.

### Claude-Code-only (no cross-harness equivalent)

Behaviors in this tier use hook events or matchers that have no tested equivalent in Codex or other harnesses. They remain Claude-Code-exclusive until a cross-harness equivalent is verified.

| Hook event | Yoke behavior | Why no cross-harness equivalent |
|------------|----------------|---------------------------------|
| `PreToolUse` (Write matcher) | Write-side path and label guardrails on Claude's `Write` tool | Codex's equivalent file-edit surface is `apply_patch`, covered as Tier 2 above; the Claude Write/Edit matchers stay Claude-specific |
| `PreToolUse` (Edit matcher) | Write-side guardrails via the Claude `Edit` tool | Same — covered cross-harness through Codex's `apply_patch` matcher in Tier 2 |
| `PostToolUse` (Write/Edit/Read) | Python-owned telemetry on non-Bash tools | Codex `PostToolUse` is only tested with the Bash matcher; non-Bash tool telemetry remains Claude-only |
| `PostToolUseFailure` (any matcher) | Python-owned telemetry for tool failures routed through a distinct event | Not a Codex hook event — OpenAI's hooks docs only document `SessionStart`, `PreToolUse`, `PostToolUse`, `UserPromptSubmit`, `Stop`. Codex Bash failures are recovered inside `PostToolUse` via text parsing + transcript reconciliation; non-Bash tool failures on Codex remain unrecovered for now. |
| `PreToolUse` (Monitor matcher) | Python-owned Monitor guardrails: (1) the `hint_monitor_relay` PreToolUse hook injects the canonical relay-only reminder text into `additionalContext`; (2) `lint_long_command_polling.evaluate_duplicate_monitor` denies a second Monitor invocation against any capture path already targeted by a Monitor in this session, whether the prior Monitor is still armed or already completed — structural enforcement of the session-spanning fire-once-per-capture contract (Monitor's tool_use completes within ~0.3s of setup but the underlying watch_tail subprocess keeps running; re-arms spawn fresh watch_tail subprocesses and orphan the prior ones). Suppression token `# lint:no-monitor-duplicate-check` is honoured ONLY as audit evidence and does NOT unblock the rule. | **Not a Codex event.** Codex has no Monitor primitive — long-running commands stream via native PTY output, so there is no `Monitor` tool to wake on per-match, no duplicate-Monitor failure mode, and no `tail -f`-style watcher arming to gate against. Codex callers run watcher wrappers (`watch_pytest`, `watch_merge`) as foreground commands and rely on PTY streaming; the floor-level rule from AGENTS.md's `## Command Output — Hard Rule` (capture-first, fallback cadence 60s -> 90s -> 120s -> max ~300s) is the complete Codex-side surface. |
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

The shared Yoke registry now supplies the current Codex-safe entrypoints (`/yoke idea`, `/yoke do`, `/yoke refine`, `/yoke advance YOK-N implementation`, `/yoke polish`, `/yoke usher YOK-N [--dry-run]`) and downstream paths (`shepherd`, `refine`, `advance`, `polish`, `usher`); [runtime/harness/codex/manifest.json](../runtime/harness/codex/manifest.json) declares Codex identity, affordances, and explicit limitations rather than copying those lists. The full Tier 1 operator surface in [docs/harness-bootstrap.md](harness-bootstrap.md) §2 is part of Codex's safe surface unless the manifest declares an additional substrate limitation.

`/yoke conduct` is not advertised as a current Codex-safe entrypoint, but the shared dispatch descriptor module remains the source for conduct-capable lanes: phase files emit one task envelope per agent, and the substrate renderer ships the canonical agent body to both `runtime/harness/claude/agents/yoke-*.md` and `runtime/harness/codex/agents/yoke-*.toml` (surfaced at `.claude/agents/` and `.codex/agents/`). The `shepherd` path remains the Codex-safe quality-gated proof lane for PM, Designer, Boss, Architect, and Simulator work.

The remaining named substrate gap is the `PostToolUseFailure` event for non-Bash Codex tools; Bash failures are recovered through transcript reconciliation as documented above.

## Canonical Session-Offer Lineage

The canonical source of `HarnessSessionOffered` and `NextActionChosen` events is the shared core session-offer path in `runtime/api/domain/sessions.py`. This path is harness-neutral -- both Claude Code CLI adapters and API callers emit the same events through the same code.

Harness-local hook output (e.g., Codex hook logs) is informational. It is never the canonical source for session lifecycle telemetry. This ensures that session-offer lineage is consistent regardless of which harness initiated the session.

## Related Docs

- [Harness Bootstrap Contract](harness-bootstrap.md) -- neutral startup expectations for all harnesses
- [Harness Adapter Template](harness-adapter-template.md) -- five-part adapter template with manifest schema
- [Session-Offer Contract](session-offer-contract.md) -- request/response envelope and identity model
- [Harness README](../runtime/harness/README.md) -- adapter directory convention
