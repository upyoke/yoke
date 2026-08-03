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
6. Confirm the print-mode gaps are still gaps (assessment doc must be
   updated if the vendor closes them): no `beforeSubmitPrompt`, no `stop`,
   no `subagentStart`/`subagentStop` despite a `Task` dispatch.

## Hook-enhanced — IDE surface

7. Open the repo in Cursor IDE, send one agent prompt, and confirm
   `beforeSubmitPrompt` (with `attachments` naming `AGENTS.md`), `stop`,
   and `afterFileEdit` (via a Write-tool edit) all fire. The session
   registers with display name `cursor-desktop`.
8. Dispatch a project subagent and confirm `subagentStart`/`subagentStop`
   carry `parent_conversation_id` equal to the top-level session id, and
   that the subagent's own tool calls arrive under the subagent session id
   with `container_session_id` resolving to the top-level session.
9. Confirm exactly ONE `harness_sessions` row exists for the whole run —
   sub-session ids must not register.

## Registration proofs

10. `python3 -m runtime.harness.harness_sessions list` shows the session
    with `executor=cursor`; `HC-executor-canonicalization` passes.
11. `yoke agents render --check` (drift gate) passes with the Cursor
    outputs enumerated.
12. Session-end defense: close the IDE window mid-session and confirm the
    session row survives when claims are held (`end_session_if_empty`
    skip path), then reactivates on the next hook event.
