## Root-cause analysis protocol

Read this before treating any failure as understood. It is the full
protocol, with the shapes that look like a root cause and are not.

## Root-Cause Analysis Protocol

When you encounter a test failure or unexpected error, you MUST diagnose before fixing. Do NOT pattern-match on error text and jump to a fix. Follow these steps in order:

1. **Read the failing assertion.** What exactly is being checked? What value was expected vs received?
2. **Query the events table for context.** Check recent tool call telemetry and anomalies: `yoke events tail --limit 20` or `yoke events anomalies --since "2 hours ago"`. Anomaly flags (nonzero_exit, benign_failure) and timing data may reveal upstream failures that caused the current symptom.
3. **Trace the code path.** Follow the function, table, schema, or data flow from the failing assertion back to the source code that creates, populates, or configures it. Read the actual source — don't guess from the error message.
4. **Identify the discrepancy.** State explicitly: "The test expects X, but the code actually does Y." For example: "Test expects TABLE but init creates VIEW", or "Test checks column `foo` but migration renamed it to `bar`."
5. **Write down the root cause** before writing any fix. Include it in your progress notes. Frame the root cause as what the SYSTEM should change to prevent recurrence — not "I made a mistake" but "the task spec referenced a nonexistent function" or "the dispatch context was missing the DB schema." If you cannot state the root cause in one sentence, you haven't finished investigating.
6. **Only then write the fix** — and verify it addresses the root cause, not just the symptom. A correct fix changes the minimum code necessary to resolve the discrepancy identified in step 4.

**Why this matters:** You are good at writing code once you understand the problem. The failure mode is spending multiple attempts guessing at fixes because you never investigated the root cause. One investigation cycle is cheaper than three fix-retry cycles.
