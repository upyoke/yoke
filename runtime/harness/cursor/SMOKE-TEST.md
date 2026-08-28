# Cursor Harness Smoke Test

Validation runbook for the Cursor adapter, mirroring
`runtime/harness/codex/SMOKE-TEST.md`. Run wrapper-only steps first; the
hook-enhanced steps assume `.cursor/hooks.json` is the rendered, materialized
copy of `runtime/harness/cursor/hooks.json`. Expected values below were measured on
Cursor IDE 3.14.7 / cursor-agent 2026.07.23-e383d2b; newer builds may move.

## Wrapper-only

1. `cursor-agent status` — confirm authenticated identity.
2. From the repo root, `cursor-agent -p "run: yoke status" --trust --force`
   — confirm the CLI executes `yoke` from the login-shell PATH.
3. `yoke sessions begin` shape: confirm a session registers with
   `executor=cursor`, display name `cursor-cli`, and appears on the board
   with the Cursor glyph.
4. Confirm `/yoke do` returns an offer with `supported_paths` derived from
   the shared registry (no manifest limitations declared).

## Hook-enhanced — CLI surface

5. Run a probe prompt via `cursor-agent -p … --force` and confirm, in order:
   - `sessionStart` fires and its `additional_context` orientation reaches
     the model (have the model echo a token from the orientation block).
   - `beforeShellExecution` deny: a command matching a deny lint is blocked
     **despite `--force`**, the model reports the `agent_message`, and
     `postToolUseFailure` records `failure_type=permission_denied`.
   - `preToolUse` fires for `Read`/`Write`/`Task` with canonicalized
     `tool_name` (`Shell` payloads arrive as `Bash` after the parser).
   - `sessionEnd` fires at process exit with `reason`/`final_status`.
   - The session row's `model` is the launch's `requested_model` when
     launch-bound; otherwise the payload's `model` (current CLI: bare id).
   - **The run itself must exit 0**, and `.cursor/hooks.json` must carry no
     `afterAgentThought` entry at all. That event fires inside the token
     stream, and a hook there breaks the stream whatever it replies:
     `cursor-agent` reports `RetriableError: WritableIterable is closed`
     after burning its reconnects. Check the exit code, not just the
     session row — an earlier revision recorded the model correctly on runs
     that were all failing. Any entry for that one event is the regression.
   - Repeat step 5 against a **stopped** session with a pending message
     (`cursor-agent --resume <id> --print …`): the run must exit 0, the
     envelope must arrive in the `sessionStart` reply's
     `additional_context`, and the turn must run the acknowledgement
     command before it ends.
6. Confirm the print-mode gaps are still gaps (assessment doc must be
   updated if the vendor closes them): no `beforeSubmitPrompt`, no `stop`,
   no `subagentStart`/`subagentStop` despite a `Task` dispatch.
6b. Confirm which config a tool call actually fires. In a workspace that
   carries BOTH `.cursor/hooks.json` and `.claude/settings.json`, Cursor
   routes every tool call through the imported Claude `PreToolUse` /
   `PostToolUse` hooks and does **not** fire its own
   `beforeShellExecution` / `afterShellExecution` / `preToolUse` /
   `postToolUse`; only `sessionStart`, `sessionEnd`, and `stop` fire on
   both configs. Verify by running one shell command and one file read and
   watching which hook commands execute. That asymmetry is why the
   imported-Claude deduplication covers lifecycle events only
   (`CURSOR_DUAL_CONFIG_RUNNER_EVENTS`): treating an imported tool hook as
   a duplicate discards the tool call's only hook invocation, which
   silently costs the session every guard, telemetry write, heartbeat, and
   inbound message injection. If a newer build starts firing both for tool
   events, widen that set rather than reintroducing a blanket skip.

## Hook-enhanced — IDE surface

7. Open the repo in Cursor IDE, send one agent prompt, and confirm
   `beforeSubmitPrompt` (with `attachments` naming `AGENTS.md`), `stop`,
   and `afterFileEdit` (via a Write-tool edit) all fire. The session
   registers with display name `cursor-desktop`.
   On an allow-path Stop the reply is `{}`. When the session holds a live
   mid-lifecycle claim and the turn is not asking the operator, the first
   Stop holds via `followup_message` (self-continuation only) and records
   `ChainEndDeferred` with `reason=promised_work_reinjected`. A second
   eligible Stop before completed tool use allows with `{}` and records
   `cap_reached=true`.
8. Dispatch a project subagent and confirm `subagentStart`/`subagentStop`
   carry `parent_conversation_id` equal to the top-level session id, and
   that the subagent's own tool calls arrive under the subagent session id
   with `container_session_id` resolving to the top-level session.
9. Confirm exactly ONE `harness_sessions` row exists for the whole run —
   sub-session ids must not register.

## Approvals and network sandbox

13. Confirm `.cursor/cli.json` and `.cursor/sandbox.json` are regular files
    (not symlinks) and that `yoke doctor` reports
    `HC-cursor-permission-config: PASS`.
14. With the taught zero-prompt posture set in Cursor's settings, run a
    network-touching `yoke` read in a fresh session and confirm it completes
    with **no** permission or network prompt and **no** `full_network`
    request. Confirm in the same session that hook telemetry recorded the
    call — the posture must not cost hook delivery.
15. Run an entire dash end to end (network `yoke` commands, git, merge) and
    confirm zero prompts throughout while `HookDispatchTelemetry` events keep
    arriving for the session.

## Registration proofs

10. `python3 -m yoke_core.hooks.sessions_cli list` shows the session
    with `executor=cursor`; `HC-executor-canonicalization` passes.
11. `yoke agents render --check` (drift gate) passes with the Cursor
    outputs enumerated.
12. Session-end defense: close the IDE window mid-session and confirm the
    session row survives when claims are held (`end_session_if_empty`
    skip path), then reactivates on the next hook event.
