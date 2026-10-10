# Simulate — dispatch contracts

Dispatch the read-only yoke-simulator with this common contract AND exactly
one mode below. Keep the complete public ref in every initial/retry prompt.

## Common contract — append to every mode

```text
Item: {public_ref}; phase: {phase}. Read-only: do not edit or file work.
Begin with SIMULATION: CLEAN or SIMULATION: GAPS FOUND, then EPIC: {public_ref}.
Native persistence refuses simulation_identity_missing or
simulation_identity_mismatch; the exact leading identity is mandatory.
Trace concrete trigger paths through actual consumers/callers, contracts and
failure paths. For every modified write trace external-call failures, safe
set -e propagation, compatibility with the previous error model and failure
tests. Findings use [CRITICAL], [WARNING], [NOTE], verified paths, root cause,
affected tasks and concrete guidance with Fix level: plan|code|mixed.
Use supplied content without re-fetching it; read authoritative parent context
when requested. No invented evidence. Uncertainty is GAPS FOUND with its reason.
```

## Plan mode

```text
Simulate the plan for {public_ref}; no code has been written.
Read authoritative parent spec/technical/worktree plans:
yoke items get {public_ref} spec
yoke items get {public_ref} technical_plan
yoke items get {public_ref} worktree_plan
Task content: {each task number, title and complete body}.
Check interface mismatches, worktree visibility, dependency feasibility,
environment/runtime differences and predicted merge sequence.
Apply the common contract and return the gap report.
```

## Integration authority — append to BOTH integration modes

```text
Tasks are complete except these explicitly excluded incomplete tasks: {list}.
Task worktree_path/branch is actual-code authority in one lane or many;
main is the base/integration target. Missing lane or supplied diff is missing
evidence, never a reason to inspect main as if it held unmerged task changes.
Read authoritative parent spec: yoke items get {public_ref} spec
Check actual exports against contracts, naming, merge/generated-file overlap
and combined state validity. Apply the common contract.
```

## Standard integration mode

```text
Simulate actual integration for {public_ref}.
Task bodies: {each task number, title and full body}.
Lane authorities: {each task, branch/worktree, worktree_path}.
Changes: {full git diff main...branch for each registered task branch}.
Statuses: {current epic-tasks list}; reviews: {each complete review}.
Apply the integration authority and common contract; return the report.
```

## Compressed integration mode

```text
Simulate actual integration for {public_ref}; task count: {task_count}.
Interfaces: {contracts per task}; overlaps: {file overlap matrix}.
Dependencies: {actual dependency edges from the registered task rows}.
Lane authorities: {each task, branch/worktree, worktree_path}.
Changes: {per-task summaries and branch git diff main...branch --stat}.
Statuses: {current task states}; reviews: {verdict and issue lines}.
Shim exports: {parse every explicit from yoke_core.board.X import (...) list
for named shim modules; include public and private names such as _BLOCKS.
The shim import list is the source of truth, not child-module internals}.
Commit-Boundary Evidence: {for each discrete-commit/NFR requirement, task or
criterion, affected path and parent-supplied git log --oneline -- path line;
if no affected path is discoverable: commit evidence unavailable: no affected
file named}. This supplied evidence is allowed; do not run archaeology.

Phase A: no tools; preliminary verdict and at most 3 candidate gaps with
severity/category/description. Phase B: at most 5 selective file reads to
verify/refute those candidates. Read only named files; a contradiction needs
explicit evidence before widening. Individual diff: git diff main...branch
-- specific-file. Adjust severity based on verification, then final report.
Forbidden: broad branch diffs, ls/find/glob enumeration, unnamed file reads,
systematic branch exploration, git log/blame unless explicitly requested.
Apply integration authority and common contract; uncertainty remains GAPS FOUND.
```
