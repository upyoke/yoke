# YOK-1227 Codex Hook Spike

Date of investigation: April 3, 2026

## Research question

Before coding the Codex side of `YOK-1227`, confirm what Codex hooks can actually do in this environment and whether they are strong enough to own any Yoke-critical behavior.

Questions:

1. Can a repo-local `.codex/hooks.json` reliably bootstrap a Codex session every time?
2. Can `SessionStart` inject shared startup context strongly enough to support Yoke bootstrap/orientation?
3. Do `PreToolUse` and `PostToolUse` fire reliably enough to support Yoke-side telemetry or enforcement?
4. Which parts of the Codex integration should be optional harness sugar versus Yoke-owned truth?

## Sources

Official docs:

- [Codex hooks](https://developers.openai.com/codex/hooks)
- [Codex config reference](https://developers.openai.com/codex/config-reference)

Local runtime:

- Codex CLI versions tested:
  - `codex-cli 0.115.0-alpha.27`
  - `codex-cli 0.118.0-alpha.2`
- Spike repo: `/tmp/codex-hooks-spike.R7g5fX`
- Repo-local hook config: `/tmp/codex-hooks-spike.R7g5fX/.codex/hooks.json`
- SessionStart payload log: `/tmp/codex-hooks-spike.R7g5fX/.codex/logs/session_start.jsonl`
- Example transcript proving injected developer context: `/Users/dev/.codex/sessions/2026/04/03/rollout-2026-04-03T09-18-36-019d537e-dc51-71f2-bd0a-2aa29db1bc78.jsonl`

## Method

I created a tiny disposable git repo with a repo-local `.codex/hooks.json` and three hook scripts:

- `SessionStart` hook writes its input payload to disk and returns `additionalContext`
- `PreToolUse` hook writes its input payload to disk
- `PostToolUse` hook writes its input payload to disk

Then I ran three local tests:

1. `codex exec` with shell disabled, asking for the startup token only
2. `codex exec` with explicit Bash usage (`pwd`, then `printf HOOK_TEST`)
3. A follow-up `codex exec` Bash run after widening the tool hook matcher to catch all occurrences

I also briefly opened interactive CLI mode, but the terminal transport here was not strong enough to make that run a good primary proof source.

After the app update, I ran a second phase of tests on `0.118.0-alpha.2` with:

- `matcher: "Bash"` restored for `PreToolUse` / `PostToolUse`
- a no-tools `UserPromptSubmit` test
- a short Bash command (`echo PREPOST_OK`)
- a slower Bash command (`sleep 3; echo SLOW_OK`)

## Official-doc baseline

As of April 3, 2026, the official Codex docs say:

- hooks are experimental and off by default
- they are enabled via `features.codex_hooks = true`
- repo-local hooks are discovered from `<repo>/.codex/hooks.json`
- `SessionStart` can emit `additionalContext`
- `PreToolUse` and `PostToolUse` currently target Bash only

The docs also describe the expected Bash-hook payload shape:

- `turn_id`
- `tool_name`
- `tool_use_id`
- `tool_input.command`
- for post-hook only: `tool_response`

## Findings

### 1. SessionStart works in `codex exec`

Observed result:

- `SessionStart` fired on every `codex exec` invocation in the spike repo
- the hook wrote one JSON line per session to `/tmp/codex-hooks-spike.R7g5fX/.codex/logs/session_start.jsonl`

Observed payload fields included:

- `session_id`
- `transcript_path`
- `cwd`
- `hook_event_name`
- `model`
- `permission_mode`
- `source`

Example observed payload:

```json
{"session_id":"019d537e-dc51-71f2-bd0a-2aa29db1bc78","transcript_path":"/Users/dev/.codex/sessions/2026/04/03/rollout-2026-04-03T09-18-36-019d537e-dc51-71f2-bd0a-2aa29db1bc78.jsonl","cwd":"/tmp/codex-hooks-spike.R7g5fX","hook_event_name":"SessionStart","model":"gpt-5.4","permission_mode":"bypassPermissions","source":"startup"}
```

### 2. SessionStart `additionalContext` reaches the model strongly enough for bootstrap

The `SessionStart` hook returned this developer context:

```text
Bootstrap token: CODEx_SESSION_START_OK. Read CLAUDE.md before editing files.
```

Evidence:

- the hook-completion output reported the injected context
- the session transcript recorded that context as a developer message
- a no-tools prompt asking for the token returned exactly `CODEx_SESSION_START_OK`

This is strong enough to support a startup/orientation reminder path.

### 3. On the older `0.115.0-alpha.27` build, turn-scoped hooks did not fire in `codex exec`

I tested Bash hooks twice:

1. with the documented `matcher: "Bash"`
2. with the matcher widened to catch all occurrences

In both runs:

- Codex did execute Bash commands successfully
- no `pre_tool_use.jsonl` log file was created
- no `post_tool_use.jsonl` log file was created
- no hook-completion messages for `PreToolUse` or `PostToolUse` appeared in output

So on that older local build, I could not empirically confirm usable Bash hook delivery even though the docs describe it.

### 4. On the older build, disabling `unified_exec` did not restore Bash hooks

I tested the same Bash-hook setup with:

- default runtime (`unified_exec = true`)
- explicit `--disable unified_exec`

Result:

- the shell-call shape changed in the transcript
- but `PreToolUse` and `PostToolUse` still never fired

With `unified_exec` enabled, the transcript showed `exec_command` function calls.

With `unified_exec` disabled, the transcript showed `shell_command` function calls.

In both cases, the pre/post hook scripts still produced zero output, including after I simplified them to write to absolute `/tmp/...` paths with no git/path logic.

### 5. On the older build, `UserPromptSubmit` also did not fire in `codex exec`

To separate "Bash hooks are broken" from "turn-scoped hooks are not running in this session type," I added a `UserPromptSubmit` hook and ran a no-tools prompt.

Observed result:

- `SessionStart` still fired
- `UserPromptSubmit` did not create any log output
- no hook-completion output for `UserPromptSubmit` appeared

This strongly suggested that, on that older `source=exec` runtime, only `SessionStart` was actually firing while turn-scoped hooks were not.

### 6. Interactive CLI mode was inconclusive in this terminal transport

I opened interactive CLI mode to check whether the missing Bash hooks were specific to `codex exec`.

That check did not produce reliable observable hook artifacts in this terminal path:

- no new SessionStart log line was captured from the interactive attempt
- no Bash hook logs appeared
- the TUI transport made the session difficult to drive cleanly enough for a strong conclusion

This means the interactive path still needs separate confirmation in a better terminal environment if we later want to depend on it for operator ergonomics.

### 7. On the updated `0.118.0-alpha.2` build, `UserPromptSubmit` fired in `codex exec`

After updating the app-bundled Codex runtime to `0.118.0-alpha.2`:

- `UserPromptSubmit` fired in `codex exec`
- the hook wrote payload data to `/tmp/codex-user-prompt-submit.jsonl`
- the payload included `session_id`, `turn_id`, `prompt`, `cwd`, and `hook_event_name`

This strongly supports the release-lineage explanation that the earlier failure was version skew rather than an inherent `codex exec` limitation.

### 8. On the updated `0.118.0-alpha.2` build, `PreToolUse` and `PostToolUse` fired in `codex exec`

Using `matcher: "Bash"` for the tool hooks, the updated local build emitted both tool hooks in `codex exec`.

Observed successful cases:

- short command: `bash -lc 'echo PREPOST_OK'`
- slower command: `bash -lc 'sleep 3; echo SLOW_OK'`

Observed `PreToolUse` payload fields included:

- `session_id`
- `turn_id`
- `tool_name: "Bash"`
- `tool_input.command`
- `tool_use_id`

Observed `PostToolUse` payload fields included:

- `session_id`
- `turn_id`
- `tool_name: "Bash"`
- `tool_input.command`
- `tool_response`
- `tool_use_id`

That means the local `codex exec` path can emit the Bash tool hooks when the runtime is new enough.

## Interpretation

The spike now supports a clearer conclusion:

### What the first-phase failure really meant

- the older `0.115.0-alpha.27` app-bundled build only proved `SessionStart`
- the absence of `UserPromptSubmit`, `PreToolUse`, and `PostToolUse` on that build was most likely version skew, not a proof that `codex exec` can never emit them

### What is good enough today on the updated local build

- repo-local `SessionStart` is useful for bootstrap/orientation
- `UserPromptSubmit` is usable for prompt-time guidance
- `PreToolUse` and `PostToolUse` are usable for optional local Bash observations
- `codex exec` on the updated build can emit all four of those hooks locally

### What still should not become Yoke’s canonical truth

- hook behavior is still experimental and version-gated
- hook availability may vary across installed Codex builds
- Yoke should therefore keep routing, ownership, fallback, and canonical telemetry in core paths rather than in Codex-local hooks

## Design implications for YOK-1227

1. Yoke core should own routing truth, ownership truth, fallback truth, and canonical ledger events.
2. Codex hooks can be used in the first slice for bootstrap and optional local observations, but not as core dependencies.
3. The Codex proving adapter should remain a thin wrapper over Yoke-owned contracts, not a second orchestration system.
4. The first proven Codex lane should work in wrapper-only mode even when hook affordances are unavailable.
5. Hook-enhanced mode can improve ergonomics on supported Codex builds.

## Recommended design constraint

For the first `YOK-1227` implementation slice:

- allow an optional repo-local Codex hook pack on supported builds
- require a safe wrapper-only path that works without hooks
- do not require any Codex hook for safe command routing
- do not require any Codex hook for ownership or fallback behavior
- do not require any Codex hook for canonical telemetry

## Follow-up questions

1. What minimum Codex version should Yoke declare for hook-enhanced mode?
2. Does interactive CLI fire the same hook set consistently in a normal terminal session outside this constrained terminal transport?
3. Is the long-term Codex entry point a SessionStart hook, a wrapper command, or both?
4. Which minimal downstream Yoke actions should Codex truthfully advertise in the first proof lane?
