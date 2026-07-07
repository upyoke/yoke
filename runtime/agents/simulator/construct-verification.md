# Simulator — Construct Verification

Reference content for the canonical simulator prompt at `runtime/agents/simulator.md`. Read and follow this file before citing any specific code construct in a gap report. Fabricated references waste downstream agent time and erode trust in simulation findings.

## What Requires Verification

Any specific reference to a codebase artifact counts as a "code construct" and must be verified before inclusion in a gap report:

- **Health check IDs** (e.g., HC-sync-failure, HC-schema-drift) — Grep for the ID in doctor scripts
- **Function/method names** (e.g., `_body_write_full`, `findByEmail`) — Grep for the definition
- **Variable and environment variable names** (e.g., `$YOKE_DB`, `$GH_TOKEN`) — Grep for assignment or usage
- **Script file paths** (e.g., `.agents/skills/yoke/scripts/foo.sh`) — Glob or Read to confirm existence
- **Config keys** (e.g., `temp_root`) and DB policy keys — Grep in the machine config contract or DB schema
- **Table and column names** (e.g., `epic_tasks.task_num`) — Grep in schema or migration files
- **Route paths, command names, event names** — Grep for the literal string

## How to Verify

Use your available tools — at least one verification attempt per construct:

- **Grep** for identifiers, function names, variable names, IDs
- **Glob** for file paths and directory structures
- **Read** to confirm a specific file contains the expected construct

## When a Construct Cannot Be Verified

**Under normal dispatch:** Do not include the gap. If a referenced construct does not exist, the gap is likely fabricated. Either drop the gap entirely or reformulate it without the unverified reference.

**Under compressed context or retry tiers:** Verification tool use may be restricted. In this case, you may include a gap that references an unverified construct, but you MUST:
1. Add an explicit `[UNVERIFIED]` tag next to the construct reference
2. Note in the gap's root cause that the reference could not be verified due to context constraints
3. Downgrade severity by one level (CRITICAL becomes WARNING, WARNING becomes NOTE)

## Examples

Bad (fabricated reference, no verification):
> GAP #3: HC-sync-failure count is not reset after successful sync

Good (verified before citing):
> *Grepped for "HC-sync-failure" across all scripts — found in python3 -m yoke_core.engines.doctor. Verified construct exists.*

Good (compressed context, explicit caveat):
> GAP #3: HC-sync-failure [UNVERIFIED] count may not reset after sync
> - **Severity:** [NOTE] (downgraded from WARNING — construct unverified under compressed context)
