# Historical obsoleted hook references

## Context

Yoke's hook runtime was unified on `runtime.harness.hook_runner` during the
hook-runner consolidation slice. Several pre-consolidation module names —
`session_hooks`, `session_hooks_register`, `codex_hooks`,
`codex_hooks_tool_events`, `hook_helpers_executor` — no longer exist as live
modules. The post-consolidation audit found two distinct classes of residue:

1. **Live residue** — references in tracked source/docs that still address
   live execution surfaces. This is bug-shaped and is owned by the live
   stale-reference and scanner-coverage backlog (separate items).
2. **Historical residue** — references in immutable or
   archive-by-design surfaces that describe past work as it was at the time
   of writing. This document addresses the policy question for class 2 only.

Concrete historical residue inventory (at the time of writing):

- **Append-only `events` ledger** — retired event-name rows still exist
  (`AgentSessionStarted=1820`, `SessionSentFirstUserPromptSubmit=1`,
  `SessionStartPayloadObserved=10`, `SessionStarted=22`,
  `WorktreeHandoffEmitted=4`). A `created_at >= post-consolidation cutover`
  filter against those names returned zero rows, confirming the residue is
  historical, not new emission.
- **Structured backlog fields** — historical hook-module names appear in
  `epic_progress_notes.body`, `epic_tasks.body`, `items.spec`,
  `items.technical_plan`, `items.test_results`, and `items.worktree_plan`.
  Full audited counts:
  ```text
  epic_progress_notes.body|codex_hooks|23
  epic_progress_notes.body|codex_hooks_tool_events|6
  epic_progress_notes.body|hook_helpers_executor|3
  epic_progress_notes.body|session_hooks|16
  epic_progress_notes.body|session_hooks_register|2
  epic_tasks.body|codex_hooks|27
  epic_tasks.body|codex_hooks_tool_events|5
  epic_tasks.body|hook_helpers_executor|4
  epic_tasks.body|session_hooks|18
  epic_tasks.body|session_hooks_register|2
  items.spec|codex_hooks|59
  items.spec|codex_hooks_tool_events|9
  items.spec|hook_helpers_executor|5
  items.spec|session_hooks|36
  items.spec|session_hooks_register|1
  items.technical_plan|codex_hooks|7
  items.technical_plan|codex_hooks_tool_events|1
  items.technical_plan|hook_helpers_executor|1
  items.technical_plan|session_hooks|3
  items.technical_plan|session_hooks_register|1
  items.test_results|codex_hooks|4
  items.test_results|codex_hooks_tool_events|2
  items.test_results|hook_helpers_executor|2
  items.test_results|session_hooks|4
  items.worktree_plan|codex_hooks|9
  items.worktree_plan|codex_hooks_tool_events|2
  items.worktree_plan|hook_helpers_executor|1
  items.worktree_plan|session_hooks|5
  items.worktree_plan|session_hooks_register|1
  ```
  These describe what the work touched at the time the field was authored.
- **Archive docs** — `docs/archive/service-migration.md`,
  `docs/archive/2026-04-03-yok-1227-codex-hook-spike.md`,
  `docs/archive/scripts.md`, `docs/archive/zero-shell-subprocess-audit.md`,
  `docs/archive/hooks.md`, `docs/archive/zero-shell-proof.md`,
  `docs/archive/shell-history.md` all contain literal historical names. The
  `docs/archive/decisions/README.md` format (`## Context`, `## Decision`,
  `## Consequences`, topic-based slugs, no ticket numbers or dates) is the
  house style this document follows.

The question this decision answers: should historical references in
immutable or archive-by-design surfaces be preserved, annotated, or rewritten?

## Decision

**Historical references in immutable and archive-by-design surfaces are
preserved as-is. They are intentional provenance, not residue to purge.**

Per surface:

### Append-only `events` ledger — preserve

The events table is an immutable audit log. Rewriting historical event rows
to a name that did not exist at the emission time would break the
"append-only ledger" contract that downstream tooling (Ouroboros, frontier,
session attribution) depends on. Retired event-name rows that predate the
consolidation cutover are correct historical evidence and stay.

### Structured backlog fields on terminal items — preserve

Backlog fields on items in terminal states (`done`, `release`, `implemented`)
record what the work touched at authoring time. Rewriting `items.spec` for a
done ticket from `codex_hooks` to `runtime.harness.hook_runner` would change
the meaning of a closed historical record and would falsify the dependency
chain for any future ticket that cites that ticket as background.

Backlog fields on **non-terminal** items (`refined-idea`, `implementing`, in
the active frontier) are a different question — those are live surfaces,
not history. If a non-terminal item's spec still names a retired hook
module, that is live residue and belongs in the live-stale-reference
follow-up scope, not this policy.

### Append-only `epic_progress_notes` — preserve

`epic_progress_notes` is structurally append-only (rows are added, never
edited, when an agent records execution context). The same preservation
logic as the events ledger applies: notes describe what was true when they
were appended.

### Archive docs (`docs/archive/**`) — preserve

Archive docs exist to describe historical state. Rewriting
`2026-04-03-yok-1227-codex-hook-spike.md` to remove the name `codex_hooks`
would defeat the purpose of the file — the spike report's value is its
fidelity to what existed at the time. Archive doc readers must already
treat the contents as a snapshot, not as a description of current state.

### Live tracked files — out of scope here

Source files, prompt surfaces, and skill bodies that name retired hook
modules in live (non-archive) execution paths are bugs and are owned by
the live-stale-reference and scanner-coverage tickets in the active
frontier. This decision does not change that scope.

## Consequences

### What does not change

- No bulk rewrite of `items.spec`, `epic_progress_notes`, `epic_tasks`,
  `items.technical_plan`, `items.test_results`, or `items.worktree_plan`
  on terminal items.
- No rewrite of any row in the `events` table.
- No rewrite of any file under `docs/archive/`.
- No new governed DB mutation profile is required by this decision.
- No live runtime behavior changes.

### What does change

- `HC-obsoleted-terms` (the live scanner) treats `docs/archive/**` as
  out-of-scope by design. References inside archive surfaces are not
  flagged because the policy here makes them intentional provenance, not
  obsoleted-term hits. A separate scanner-scope follow-up implements the
  exclusion if it does not already exist.
- The same scanner treats backlog fields on **terminal** items as
  out-of-scope, and backlog fields on non-terminal items as in-scope.
  Without that distinction, the scanner would fire on every historical
  spec that touched the consolidation, none of which represents live
  residue.
- Future agents reading historical content under `docs/archive/`,
  terminal-item structured fields, or older `events` rows must treat the
  retired hook-module names as **historical fact, not as guidance about
  live surfaces**. The live module is `runtime.harness.hook_runner`.

### Follow-ups required

- A follow-up scanner item has been filed so that `HC-obsoleted-terms`
  excludes `docs/archive/**` and
  excludes backlog-field surfaces on terminal items. The implementation
  scope is scanner-only — no DB rewrite, no historical-doc rewrite — and
  remains separate from the live-residue and scanner-coverage tickets
  already in the frontier.
- No DB-cleanup follow-up is filed: this decision intentionally rejects
  bulk rewriting of historical structured fields, so AC-5's conditional
  ("if any DB/backlog-field cleanup is chosen") does not apply.

### Auditability

`HC-obsoleted-terms` work after this decision must distinguish three
classes of hit:

1. **Live residue** — tracked source, prompt, or doc file outside
   `docs/archive/` that names a retired surface in a live context. Fix in
   place.
2. **Non-terminal backlog field residue** — `items.spec` (or sibling
   structured fields) on an item in the active frontier that names a
   retired surface in current planning text. Fix via the standard refine
   or amend path.
3. **Intentional historical reference** — `events` row, terminal-item
   backlog field, or `docs/archive/**` file that names a retired surface.
   No action; this decision is the authoritative reason.

When a future audit surfaces a hit of class 3, link this decision rather
than reopening the policy question.
