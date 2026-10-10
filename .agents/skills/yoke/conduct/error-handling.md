# Conduct — named failures

Failures name the systemic contract and recovery. Before retry/halt, read
yoke events tail --limit 20 and file an immediate field-note; never blame an
agent or hide command stderr. Preserve evidence and lane state.

| Failure | Scope and action |
|---|---|
| Missing pin/spec/graph or failed sync | Halt before dispatch; pinned authoring/registered sync repair. |
| Same-worktree/dependency conflict | Exclude affected candidate; independent chains proceed. |
| Task claim_conflict / unknown head_dispatch | No lane writes; named holder/read recovery. |
| Submission defect | Same-attempt submit-only bounded remediation. |
| Genuine FAIL | Retry through configured total attempts; exhaustion fails that task. |
| Unresolved main merge after Engineer repair | Halt affected task; retain resolved siblings. |
| Exhausted Tester output | Named direct-verification exception; no fabricated PASS. |
| Exhausted Simulator output or attestation/readback failure | HALT exact diagnostic; no direct simulation fallback. |
| Auto-fix/one amend cycle exhausted | HALT, preserved lanes and remaining report. |
| Blocking QA unavailable | Operator repair or explicit authorized waiver; no auto-waive. |
| Unrecoverable command failure | HALT with capture and named recovery. |

Every halted report lists failed, blocked (reasons) and not-started tasks. The
configured attempt limit owns retries, not a contradictory second-FAIL rule.

Engineer implements; Tester/Simulator are read-only; Architect only through
Simulate auto-fix. Render harness descriptors without isolation/new lanes.
Parallel tasks use their own exact registered lane and claims. State lives in
registered item/task/QA/chain surfaces, not filesystem status or worktree DB.
Pipeline task writes retain attempts/history/derive; generic writes are not
equivalent. No handpush, done-transition, GitHub issue closure or lane removal.

Immediate autonomous continuation follows each return; only a named halt or
explicit operator decision stops the loop. At the pinned handoff refresh the
skill, verify claim release and let the delivery binding own landing/completion.
