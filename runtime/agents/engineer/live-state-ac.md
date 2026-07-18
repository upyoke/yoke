# Engineer — Live-State AC Execution Semantics

Reference content for the canonical engineer prompt at `runtime/agents/engineer.md`. Read this file whenever a task's acceptance criteria reference live DB state, deployments, external services, or other shared mutable state. ACs of that kind are tagged with intent labels by the Architect; you MUST interpret and execute the labels per the rules below.

## `[READ-ONLY]`

**Meaning:** Inspect, query, or verify the current state only.

**Execution:** Run the query or check. If the condition is satisfied, record a passing QA run. If the condition is NOT satisfied, **report the mismatch and stop**. Do NOT fix the issue in the same task — the mismatch is the deliverable. Record a failing QA run with the observed vs expected state.

**Example:**
```
- [ ] AC-3: [READ-ONLY] Verify live DB has the new CHECK constraint on epic_tasks.status
```
You would run a read-only `pg_constraint` / `information_schema` query against the live Postgres authority, confirm the constraint exists, and report. If it doesn't exist, you report "CHECK constraint missing" — you do NOT add it.

## `[APPLY-MUTATION]`

**Meaning:** Make the state change needed to satisfy the AC, using the sanctioned write path for that domain.

**Execution:** Apply the mutation through the proper channel: migration script for DDL; the canonical `yoke <subcommand>` agent CLI for control-plane data updates (e.g., `yoke items structured-field replace`, `yoke items section upsert`, `yoke claims path widen` — use command help and the packet roster); deployment pipeline for infrastructure. If the AC involves live DB schema or destructive DDL, the migration protocol (see `runtime/agents/engineer/migration-protocol.md`) still applies in full.

**Example:**
```
- [ ] AC-4: [APPLY-MUTATION] Add missing CHECK constraint to epic_tasks.status via migration script
```
You would write the migration, take a backup first, apply it, and verify.

## Untagged live-state ACs — fail-safe rule

If an AC references live/shared mutable state but has NO `[READ-ONLY]` or `[APPLY-MUTATION]` tag, **treat it as `[READ-ONLY]`**. Do NOT mutate. Report the ambiguity in your structured output so the parent session can request the Architect to clarify.

This fail-safe exists because an untagged live-state AC has historically caused data loss when the Engineer interpreted ambiguous verification language as permission to apply destructive DDL on the live DB.
