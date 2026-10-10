# Hook Parity Map (internal)

Use this source-maintainer map to trace a native hook to its shared Yoke
behavior. Current availability is declared by each
`runtime/harness/<harness-dir>/manifest.json`, not by a copied event matrix.
The [hook guide](hooks.md) owns runtime teaching;
[bootstrap](harness-bootstrap.md) and the
[adapter contract](harness-adapter-template.md) own startup and adapter shape.

## Capability authority

The manifests own identity, runtime minima, optional local affordances,
bootstrap mechanisms, worktree enablement, telemetry and unsupported paths.
The shared registry owns command and stage-skill availability, including
`/yoke implement` and `/yoke conduct`. A hook gap
does not imply a missing stage skill or subagent path: inspect the manifest
and the shared dispatch descriptor separately. Core lifecycle/claim
correctness works without hooks; missing hooks use the declared wrapper-only
mode, while unsupported paths return a named unsupported answer to core.

## Harness wake capability

Watcher subscription and continuation depend on these generated facts:

<!-- BEGIN GENERATED: harness-wake-capability -->
Wake capability is a manifest fact, not prose. Source of truth:
`agent_wake` in `runtime/harness/<harness-dir>/manifest.json`, rendered from
`yoke_contracts.harness_wake_capability`. Change the contract and re-render; never
restate one of these facts on a document's own authority.

| Harness | Idle wake (resume an ended turn) | Timer wake | Verified on |
|---|---|---|---|
| `claude-code` | supported (`Monitor`) | supported (`ScheduleWakeup`) | `claude-cli` |
| `codex` | none | none | `codex-cli` |
| `cursor` | supported (`notify_on_output`) | none | `cursor-cli` |

Evidence behind each row:

- `claude-code` — Monitor and ScheduleWakeup are first-class model-facing tools. Every stdout line a Monitor filter matches resumes the turn, which is what the main-session long-command rule is built on.
- `codex` — Live probe: foreground exec_command/PTY output streams only while the turn stays active; backgrounding with (...) & returns a prompt but stdout does not resume the model; a detached nohup child vanished when its command invocation ended and wrote zero lines. Continuations are an exec_command session_id plus explicit write_stdin polling; none resumes a turn after it ends.
- `cursor` — Live probe: the session ends its turn after a Shell call with block_until_ms=0 and a notify_on_output pattern, then receives system_notification pattern matches while idle — a working equivalent of Claude's Monitor. No timer wake was observed.
<!-- END GENERATED: harness-wake-capability -->

## Shared dispatch and native adapters

Generated hook commands invoke `yoke hook evaluate <event>` once per native
event/matcher. The Python-owned runner walks
`yoke_contracts.hook_runner.hook_ordering.ordered_pipeline_for`; adapters do
not copy lint ordering, per-policy shell choreography or runtime import paths.
Session start/prompt boundaries register identity and inject orientation;
pre-tool hooks apply command/write guardrails; post-tool hooks record
telemetry; Stop attempts bounded empty-session ending. Claimed or
chain-pending sessions retain custody. Registration separates requested
identity from provider-attested served facts.

Commands use non-login `/bin/sh` and the configured XDG launcher directory,
`~/.local/bin`, Homebrew and system paths, avoiding interactive shell startup
inside native hooks. Codex's generated commands pin
`YOKE_EXECUTOR=codex YOKE_PROVIDER=openai`; Cursor pins `YOKE_EXECUTOR=cursor`
with provider derived from payload. Claude Write/Edit and Codex `apply_patch`
are distinct native tools feeding shared write-side authority.

Cursor's Bash chain uses `beforeShellExecution`, avoiding a second Shell
pre-tool chain. Allow-time context is available at `sessionStart` and
`postToolUse`; advisory-only pre-tool hints are explicitly omitted where
there is no channel. Native event coverage differs between IDE and print-mode
CLI. The [dated Cursor assessment](harness-cursor-assessment.md) retains the
measured matrix, deny behavior and subagent payload folding; current
manifest/runtime contracts select behavior. Streaming thought events have no
configured hook. Cursor command bytes must satisfy the manifest's JSONC
restrictions or hooks may disappear before dispatch.

## Hook trust and lane lifecycle

Codex trust is keyed by literal hook path and normalized handler identity.
Project install/refresh mints current hashes only for the Yoke-authored file
it installs, replacing that path's stale hashes. Failure to update config
refuses with the native Hooks/Trust recovery. Changes outside that install
boundary remain the operator's trust decision.

A lane has a different literal path. Preparation mirrors only the main
checkout's current byte-identical trust; relay launches use the manifested
opening-hook enablement so registration is not stranded. Removal deletes the
lane's hook tables and project record. `yoke codex hook-trust sweep --dry-run`
reports deleted-path residue; the non-dry-run form removes only stale
absolute paths, preserving existing paths and unrecognized third-party
entries. Read its `--help` before cleanup. `HC-worktree-hook-trust` checks
current hashes and names sweep recovery for residue.

Claude's trust boundary is the project directory, with
`hasTrustDialogAccepted` in its project record rather than a per-hook hash
store. Cursor workspace trust is separate from hook approval; Yoke inventory
records its hook `approval_state=not_applicable`. The manifests and installed
configuration own enablement; this map grants no trust or authorization.

## Codex failure telemetry

Codex has no separate `PostToolUseFailure` event in the tested surface.
The post-tool parser recovers Bash failures in order:

1. Parse a literal `Exit code N` in `tool_response`.
2. With no explicit error/exit code, recognize command-prefixed hard-failure
   text (`No such file or directory`, `command not found`, `Permission denied`)
   only on `PostToolUse`, recording a failed event with sentinel exit code `1`.
3. If still unreconciled and `transcript_path`/`tool_use_id` exist, read a
   bounded 2MB rollout tail and match `exec_command_end.call_id` to that tool
   id. Its exit code/status catches silent failures such as `false`.

I/O, JSON, missing-field and schema errors leave the unreconciled result;
they do not crash the hook. The transcript format is a measured native
artifact, not a vendor-published schema. Non-Bash failure parity remains a
separate substrate limitation. Historical event rows are not rewritten;
synthetic canonical-DB telemetry is a separate concern. Existing regressions:
[Bash classification](../runtime/api/test_observe_codex_bash.py) and
[bounded transcript reconciliation](../runtime/api/test_observe_codex_transcript.py).

## Long commands and lifecycle evidence

Claude's Monitor guardrails reject bare watcher `tail -f`/`tail -F`, enforce
one subscription per capture and supply the relay reminder. Denial
suppression is audit-only. These native Monitor behaviors do not create a
Monitor tool on another harness. Codex continues the same yielded
`exec_command` handle with `write_stdin` while its turn remains active;
ending the turn is not an output-driven wake. Current watcher recipes and
capture discipline live in [full-suite authority](testing-verification/full-suite-authority.md)
and the installed agent rules. Never start a second invocation beside a live
one or infer completion from partial output.

Canonical session lifecycle and claim events originate in shared core
operations. Local hook/transcript logs are disposable diagnostics and are
never gate authority. Current agent bodies are rendered from the shared
registry/dispatch contract into every supported harness; manifests declare
limitations instead of this document maintaining a second safe-command or
agent roster.

## Related owners

- [Harness manifest schema](../runtime/harness/manifest-schema.md)
- [Harness adapter directory contract](../runtime/harness/README.md)
- [Canonical hooks](hooks.md)
- [Bootstrap orientation](harness-bootstrap.md)
