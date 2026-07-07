# Agent Invocation Conventions

Shared conventions for any SKILL or agent that invokes subagents and parses structured output.

## Canonical Pattern: Unparseable Output Escalation

Use this retry/escalation pattern whenever a subagent is expected to return parseable structured output (verdict blocks, result headers, machine-readable markers).

1. First invocation: use the agent definition default model.
2. If output is unparseable, retry with stronger instructions and increment a failure counter scoped to:
   - item/context id
   - agent type
   - transition or phase
3. After 2 prior unparseable outputs from the same agent in the same scope, invoke with `model: "opus"`.
4. Log the escalation and failure count in persistent state (item body notes or DB record), not only transient console text.
5. Reset the counter after a parseable output is successfully produced.

## Canonical Examples

`conduct/SKILL.md` is the canonical implementation reference:

**`conduct/SKILL.md`** (track orchestrator and single-item):
- Per-item Tester output gate and model escalation in the Engineer/Test loop
- Retry-once-then-halt semantics per item

When implementing this convention in other skills, mirror conduct behavior:
- Treat "no parseable output" as distinct from a legitimate FAIL verdict.
- Retry deterministically.
- Escalate to opus only after repeated parse failures.

## Side-Channel Pattern: Durable Verdict Echo

When an agent produces a critical structured output (verdict, status keyword), the agent should **echo** the verdict via a Bash tool call in addition to including it in text output:

```bash
echo "FINAL_BOSS_VERDICT: GO"
```

This creates a durable marker in the tool call history that survives two failure modes:
1. **Turn-limit cutoff** — agent hits `maxTurns` before producing final text, but the echo happened in an earlier turn.
2. **Context compression** — the agent's final text message is truncated, but tool call results are preserved.

**For callers:** When parsing agent output, first check the text response for the structured block. If unparseable, scan tool call results for the side-channel marker (`FINAL_BOSS_VERDICT:`, `TESTER_VERDICT:`, etc.). The side-channel is authoritative if text output is missing.

## maxTurns Guidance

Set `maxTurns` in agent definitions based on expected workload:

| Agent type | Typical tool calls | Recommended maxTurns |
|---|---|---|
| Read-only evaluators (Boss, Final Boss) | 20-40 | 50 |
| Implementers (Engineer) | 30-80 | 100 |
| Lightweight validators (Tester) | 10-20 | 30 |

Signs that `maxTurns` is too low:
- Agent completes but verdict/output is missing from the return text
- Agent "wanders" trying workarounds for failed queries instead of finishing
- Caller retries the same agent multiple times with no parseable output

## PostToolUse Telemetry Standard

All 6 worker agents (Engineer, Tester, Simulator, Architect, PM, Designer) have `observe-tool.sh` wired as a PostToolUse and PostToolUseFailure hook in their frontmatter. This emits structured events to the `events` table for every tool call.

**Hook composition:** Engineer has two PostToolUse hooks: `on-bash-complete.sh` (Bash-specific, with matcher) and `observe-tool.sh` (all tools, no matcher). Claude Code composes them independently — each receives the hook JSON on stdin separately.

**Frontmatter pattern (all worker agents):**
```yaml
hooks:
  PostToolUse:
    - hooks:
        - type: command
          command: ".claude/skills/yoke/scripts/observe-tool.sh"
  PostToolUseFailure:
    - hooks:
        - type: command
          command: ".claude/skills/yoke/scripts/observe-tool.sh"
```

**Engineer-specific addition** (Bash progress sync preserved alongside telemetry):
```yaml
hooks:
  PostToolUse:
    - matcher: "Bash"
      hooks:
        - type: command
          command: ".claude/skills/yoke/scripts/on-bash-complete.sh"
    - hooks:
        - type: command
          command: ".claude/skills/yoke/scripts/observe-tool.sh"
```

**Events emitted:**
- `ToolCallCompleted` — every successful tool call (PostToolUse)
- `ToolCallFailed` — every failed tool call (PostToolUseFailure)
- `AnomalyDetected` — secondary event when anomaly flags are present

**Anomaly flags:**
- `nonzero_exit` — tool returned nonzero exit code
- `generated_view_write` — Write/Edit to generated view files (`backlog/*.md`, `BOARD.md`, `designs/*.md`)
- `nested_cli` — command spawned a nested `claude` CLI process
- `retry_loop` — registered in enum, detection deferred (requires cross-event state)
- `hung_subagent` — registered in enum, detection deferred

**Session lifecycle events** (not in agent frontmatter, in global hooks):
- `AgentSessionStarted` — emitted by `harness-session-start.sh` (UserPromptSubmit)
- `AgentSessionStopped` — emitted by `on-agent-stop.sh` (SubagentStop)

**Event registry enforcement:** All event names emitted via `emit-event.sh` must be registered in the `event_registry` table. The `lint-event-registry.sh` PreToolUse hook (active in all sessions via `.claude/settings.json`) validates event names at emit time. Unregistered events are denied with a message showing the `yoke-db.sh events registry add` command. When adding a new event type, register it first via `yoke-db.sh events registry add` before emitting.
