# Usher — conflict recovery

Read actual watcher error/checkout/branch/default target. Preserve state and
continue same Git operation; never start another merge/rebase beside it.
Sequential lanes avoid compounded conflicts. No blanket branch/main preference:
reconcile current function and intent.

Exit3 emits CONFLICT|path|classification:

| Classification | Meaning |
|---|---|
| generated/doc/yoke-gen (auto) | Deterministic generated resolution. |
| additive (auto) | Independent additions AND union accepted by real format. |
| doc (branch-modified, manual) | Intentional branch prose needs review. |
| overlapping (needs agent judgement) | Edits overlap or union would duplicate invalid YAML/JSON/TOML keys. |

Inspect both edits; preserve independent/structural imports, exports and
registrations, regenerate derived files from canonical owners, verify format
and behavior. Stage exact resolved paths and commit, or continue the active
rebase, then rerun the same internal merge procedure. If no Git operation is
active and printed recovery calls for integration, fetch verified current
project upstream first and merge/rebase the actual declared default branch.
No guessed main, discarded state or generated-file union without validation.

Hard exit1 (tests, push, CI or other failure) retains engine cleanup/outcome. Read
exact phase and lane, fix current-item verification/conflict, commit, then
resume; successful prior lanes skip. Complex/uncertain intent stops with
paths, evidence and required operator decision, not a guessed resolution.
Claim/dependency reconciliation precedes override; no planned future-claim
waiver or override. Only authorized irreducible live collision recovery applies.

Engine publication uses force-with-lease where rebase requires it; workers
never push by hand. The documented CI timeout is 30 minutes; actual receipt/
named runner timeout owns the outcome. Never infer timeout from silence or
poll external state instead of the running handle.
