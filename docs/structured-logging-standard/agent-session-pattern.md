## Section F: Agent Session Transcript Pattern

Agent and harness session transcripts are reconstructed from the `events` table by querying rows for a given `session_id`. The practical sequence today is centered on tool-call lifecycle rows plus optional session bookends. Cross-harness parity is still incomplete on some paths.

### Event Sequence

A fully instrumented harness session can produce the following events in order:

```
HarnessSessionSentFirstUserPromptSubmit (0..1 -- session open when session hooks are wired)
 HarnessToolCallStarted (0..N -- one per attempted tool use when PreToolUse coverage exists)
 HarnessToolCallDenied (0..N -- PreToolUse denial rows on hook paths)
 HarnessToolCallCompleted (0..N -- one per successful tool use)
 HarnessToolCallFailed (0..N -- one per failed tool use)
 HarnessToolCallStructuredExit (0..N -- expected flow-control exits)
HarnessSessionStopped (0..1 -- session close when stop hooks are wired)
```

### Event Definitions

**HarnessSessionSentFirstUserPromptSubmit**

Emitted when an agent session begins (augmented `harness-session-start.sh`).

```json
{
 "event_name": "HarnessSessionSentFirstUserPromptSubmit",
 "event_kind": "system",
 "event_type": "session_lifecycle",
 "event_outcome": null,
 "source_type": "agent",
 "severity": "INFO",
 "agent": "engineer",
 "item_id": "42",
 "task_num": 3,
 "worktree_path": "/Users/dev/yoke/.worktrees/YOK-N",
 "context": {
 "dispatch_attempt": 1,
 "actor_role": "engineer"
 }
}
```

The `actor_role` field is populated on tool-call hook events fired during a dispatched subagent's turn so audit consumers can distinguish parent-turn calls from subagent-delegated calls within the same `session_id`. Parent-turn calls omit the field.

**HarnessToolCallStarted**

Emitted by the PreToolUse timing hook when the harness provides `tool_use_id`.

```json
{
 "event_name": "HarnessToolCallStarted",
 "event_kind": "system",
 "event_type": "tool_call",
 "event_outcome": "started",
 "source_type": "hook",
 "severity": "INFO",
 "tool_name": "Bash",
 "session_id": "claude-code-20260315T143000Z-12345",
 "tool_use_id": "call_abc123",
 "hook_event_name": "PreToolUse"
}
```

**HarnessToolCallCompleted**

Emitted by PostToolUse hook on every successful tool call.

```json
{
 "event_name": "HarnessToolCallCompleted",
 "event_kind": "system",
 "event_type": "tool_call",
 "event_outcome": "completed",
 "source_type": "hook",
 "severity": "INFO",
 "agent": "engineer",
 "tool_name": "Bash",
 "session_id": "claude-code-20260315T143000Z-12345",
 "tool_use_id": "call_abc123",
 "hook_event_name": "PostToolUse",
 "duration_ms": 342,
 "context": {
 "detail": {
 "command_preview": "npm test",
 "exit_code": 0,
 "output_bytes": 4096
 }
 }
}
```

**HarnessToolCallFailed**

Emitted by PostToolUseFailure hook on every failed tool call.

```json
{
 "event_name": "HarnessToolCallFailed",
 "event_kind": "system",
 "event_type": "tool_call",
 "event_outcome": "failed",
 "source_type": "hook",
 "severity": "WARN",
 "agent": "engineer",
 "tool_name": "Bash",
 "session_id": "claude-code-20260315T143000Z-12345",
 "tool_use_id": "call_abc123",
 "hook_event_name": "PostToolUseFailure",
 "exit_code": 1,
 "duration_ms": 1200,
 "anomaly_flags": "nonzero_exit",
 "context": {
 "detail": {
 "command_preview": "npm test",
 "exit_code": 1,
 "error_output": "Error: test suite failed"
 }
 }
}
```

**HarnessToolCallDenied**

Emitted by `yoke_core.domain.observe` (denial path) when a PreToolUse hook denies a tool call.

```json
{
 "event_name": "HarnessToolCallDenied",
 "event_kind": "audit",
 "event_type": "tool_call",
 "event_outcome": "denied",
 "source_type": "hook",
 "severity": "WARN",
 "tool_name": "Bash",
 "context": {
 "detail": {
 "hook": "lint-main-commit",
 "check_id": "impl_on_main",
 "reason": "Implementation commit denied on main"
 }
 }
}
```

**HarnessToolCallStructuredExit**

Emitted when a failed command is reclassified as expected flow control rather than a real failure.

```json
{
 "event_name": "HarnessToolCallStructuredExit",
 "event_kind": "system",
 "event_type": "tool_call",
 "event_outcome": "failed",
 "source_type": "agent",
 "severity": "INFO",
 "tool_name": "Bash",
 "exit_code": 2
}
```

**HarnessSessionStopped**

Emitted when an agent session ends (`python3 -m yoke_core.domain.agent_stop`).

```json
{
 "event_name": "HarnessSessionStopped",
 "event_kind": "system",
 "event_type": "session_lifecycle",
 "event_outcome": "completed",
 "source_type": "agent",
 "severity": "INFO",
 "context": {
 "hook": "agent_stop",
 "auto_committed": false,
 "dispatch_type": "epic",
 "stop_reason": "completed",
 "epic_id": 42,
 "task_num": 3,
 "final_status": "done"
 }
}
```

### Canonical SQL Queries

#### Session Reconstruction

Retrieve the full transcript for a specific session:

```sql
SELECT
 event_name,
 created_at,
 event_outcome,
 severity,
 tool_name,
 duration_ms,
 anomaly_flags,
 envelope
FROM events
WHERE session_id = :session_id
ORDER BY created_at ASC;
```

#### Session Summary

Aggregate metrics for a session:

```sql
SELECT
 session_id,
 agent,
 item_id,
 task_num,
 MIN(created_at) AS session_start,
 MAX(created_at) AS session_end,
 SUM(CASE WHEN event_name = 'HarnessToolCallStarted' THEN 1 ELSE 0 END) AS tools_started,
 SUM(CASE WHEN event_name = 'HarnessToolCallDenied' THEN 1 ELSE 0 END) AS tools_denied,
 COUNT(*) FILTER (WHERE event_name = 'HarnessToolCallCompleted') AS tools_succeeded,
 COUNT(*) FILTER (WHERE event_name = 'HarnessToolCallFailed') AS tools_failed,
 COUNT(*) FILTER (WHERE event_name = 'HarnessToolCallStructuredExit') AS structured_exit_count,
 COUNT(*) FILTER (WHERE anomaly_flags IS NOT NULL AND anomaly_flags <> '') AS anomaly_count,
 SUM(duration_ms) FILTER (WHERE event_name LIKE 'ToolCall%') AS total_tool_ms
FROM events
WHERE session_id = :session_id
GROUP BY session_id, agent, item_id, task_num;
```

Note: the control-plane backend (Postgres) supports `FILTER (WHERE ...)` natively, so the query above runs as-is. A non-Postgres validation surface may lack `FILTER` — use the `SUM(CASE WHEN ... THEN 1 ELSE 0 END)` equivalent there:

```sql
SELECT
 session_id,
 agent,
 item_id,
 task_num,
 MIN(created_at) AS session_start,
 MAX(created_at) AS session_end,
 SUM(CASE WHEN event_name = 'HarnessToolCallStarted' THEN 1 ELSE 0 END) AS tools_started,
 SUM(CASE WHEN event_name = 'HarnessToolCallDenied' THEN 1 ELSE 0 END) AS tools_denied,
 SUM(CASE WHEN event_name = 'HarnessToolCallCompleted' THEN 1 ELSE 0 END) AS tools_succeeded,
 SUM(CASE WHEN event_name = 'HarnessToolCallFailed' THEN 1 ELSE 0 END) AS tools_failed,
 SUM(CASE WHEN event_name = 'HarnessToolCallStructuredExit' THEN 1 ELSE 0 END) AS structured_exit_count,
 SUM(CASE WHEN anomaly_flags IS NOT NULL AND anomaly_flags <> '' THEN 1 ELSE 0 END) AS anomaly_count,
 SUM(CASE WHEN event_name LIKE 'ToolCall%' THEN duration_ms ELSE 0 END) AS total_tool_ms
FROM events
WHERE session_id = :session_id
GROUP BY session_id, agent, item_id, task_num;
```

#### Task Analysis

All sessions for a specific epic task:

```sql
SELECT
 session_id,
 agent,
 MIN(created_at) AS session_start,
 MAX(created_at) AS session_end,
 COUNT(*) AS event_count,
 SUM(CASE WHEN anomaly_flags IS NOT NULL AND anomaly_flags <> '' THEN 1 ELSE 0 END) AS anomaly_count
FROM events
WHERE item_id = :item_id
 AND task_num = :task_num
GROUP BY session_id, agent
ORDER BY session_start ASC;
```

#### Performance Analysis

Tool call duration distribution by tool:

```sql
SELECT
 tool_name,
 COUNT(*) AS call_count,
 AVG(duration_ms) AS avg_ms,
 MIN(duration_ms) AS min_ms,
 MAX(duration_ms) AS max_ms,
 SUM(CASE WHEN event_outcome = 'failed' THEN 1 ELSE 0 END) AS failure_count
FROM events
WHERE event_name LIKE 'ToolCall%'
 AND created_at >= :since
GROUP BY tool_name
ORDER BY call_count DESC;
```

#### Anomaly Clusters

Recent anomalies grouped by flag and agent:

```sql
SELECT
 anomaly_flags,
 agent,
 COUNT(*) AS occurrence_count,
 MIN(created_at) AS first_seen,
 MAX(created_at) AS last_seen
FROM events
WHERE anomaly_flags IS NOT NULL
 AND anomaly_flags <> ''
 AND created_at >= :since
GROUP BY anomaly_flags, agent
ORDER BY occurrence_count DESC;
```

### Key Design Decisions

- **session_id is the primary key for session analysis.** All events in a session share the same `session_id`. Query `WHERE session_id = :id` for a complete transcript.
- **item_id + task_num is the primary key for task analysis.** Multiple sessions may work on the same task (retries, multi-session work). Query `WHERE item_id = :id AND task_num = :num` for all sessions related to a task.
- **Anomalies live on the primary tool-call row.** Yoke stores anomaly signals in `anomaly_flags` on `HarnessToolCallCompleted`, `HarnessToolCallFailed`, or `HarnessToolCallStructuredExit` rather than emitting a second anomaly event.
- **`created_at` is the first-class table timestamp.** `event_time` lives in the JSON envelope; use `created_at` for SQL against the live `events` table.
- **Durations are always in milliseconds.** The `duration_ms` field on `HarnessSessionStopped` represents total session wall time. On `HarnessToolCallCompleted`/`HarnessToolCallFailed` it represents tool execution time.

---
