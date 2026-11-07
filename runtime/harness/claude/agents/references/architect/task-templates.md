# Technical plan and task templates

## Technical Plan

Under `## Technical Plan`, in order: `### Technical Approach`,
`### Architecture Decisions`, `### Dependencies`, `### Task Summary` (table),
`### FR Traceability` (table), `### Task Dependency Graph`,
`### Interface Contracts`, `### Acceptance Criteria`, `### Risk Assessment`.

## Task

````markdown
---
worktree: PREFIX-{N}
context_estimate: M
dependencies: none
---
# Task {NNN}: {Title}
## Description
{verified paths and semantic anchors}
## Acceptance Criteria
- [ ] AC-1: {specific, independently testable behavior}
## Test Plan
{unit, integration and applicable manual checks}
## Interface Contract — Provides
{path, exports, signatures and exact behavior}
## Interface Contract — Expects
{upstream task, path, exports, signatures and behavior required}
## Cross-Script Contracts
{only when a boundary changes; see cross-script-contracts.md}
## Watch Out For
{only when needed: boundary, error or data gotchas and their mitigation}
## Documentation Requirements
{new docs and every existing doc to update}
## Files Touched
- {create|modify|delete} `{exact/path}` — {responsibility}
````

The front matter carries the values the parent passes to `yoke workflow-item
epic-task add`. `worktree` is `PREFIX-{N}` for a single lane, otherwise
`PREFIX-{N}-{short-kebab-concern}`, shared by every task in that lane.
`context_estimate` is XS, S, M or L. `dependencies` lists task numbers or
`none`; a cross-lane dependency holds the consumer until its blocker merges.

`## Files Touched` is the task's only file list: coverage, claims and lane
narrowing parse it. One bullet per file with the path in backticks; a task that
touches no repository file writes exactly `None — no repository files`.

A consumer-proof criterion uses the release-time exact-pair gate
(`.yoke/docs/verification/consumer-proof.md`), not a consumer build before merge.
