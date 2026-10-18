# Technical plan and task templates

Read before authoring a technical plan or task specification. Preserve the
complete contracts, traceability and metadata below.

## Technical Plan Template

Under `## Technical Plan`, in order:
`### Technical Approach`, `### Architecture Decisions`, `### Dependencies`,
`### Task Summary`, `### FR Traceability`, `### Task Dependency Graph`,
`### Interface Contracts`, `### Acceptance Criteria`, `### Risk Assessment`.
Task Summary and FR Traceability are tables. Every spec FR maps to tasks and
epic ACs, every epic AC to task ACs. Without FR identifiers enumerate R-1 etc.
No unmapped requirement: implement or evidence-backed Coverage Note exclusion.

## Task Template

Every task carries required parseable YAML and all sections:

````markdown
---
worktree: PREFIX-{N}
context_estimate: M
dependencies: none
---
# Task {NNN}: {Title}
## Description
{verified paths and semantic source anchors; never line numbers}
## Acceptance Criteria
- [ ] AC-1: {specific independently testable behavior}
## Test Plan
{unit, integration and applicable manual checks}
## Interface Contract — Provides
{path, exports, types/signatures and exact behavior}
## Interface Contract — Expects
{upstream task/path, exports, types/signatures and behavior required}
## Cross-Script Contracts
{conditional: exact data schema/nesting, arguments, exits and transforms;
subprocess environment/cwd, old/new error models and caller guards}
## Watch Out For
{conditional boundary/error/data gotchas with references and mitigation}
## Documentation Requirements
{new docs and all existing docs to update}
## Files Touched
- {create|modify|delete} `{exact/path}` — {responsibility}
````

`## Files Touched` is the task's only file list: coverage, claims and lane
narrowing parse it. One bullet per file with the path in backticks; a task
touching no repository file writes exactly `None — no repository files`.

Omit conditional sections when irrelevant. Include functional naming obligation
where creating/renaming live surfaces. Enabled File Budget names each planned
file and single responsibility, with sizing/headroom decisions before implementation.
Live-state ACs use exactly `[READ-ONLY]` (inspect; mismatch report/stop, no repair)
or `[APPLY-MUTATION]` (sanctioned domain write). No alternate spellings. Untagged
live state defaults read-only. State recovery/rollback for all mutations.

worktree is bare PREFIX-{N} for single lane, otherwise PREFIX-{N}-{short-kebab-
concern}; all tasks in one lane share its value. context_estimate XS/S/M/L,
never XL. dependencies are comma-separated task ids or none; cross-lane upstream
ids gate consumer activation until required merge. Smaller coherent tasks are
safer than oversized multi-concern work; beyond about20 propose epic split.
