---
name: idea
description: Create a new backlog item with a PREFIX-N ID. Infers project, workflow, priority, and flow from context.
argument-hint: "[--dry-run] [--workflow issue|epic|blitz|task] {title}"
---

# /yoke idea [--dry-run] [--workflow issue|epic|blitz|task] {title}

Create a new backlog item and assign it the next available PREFIX-N ID.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Arguments

- `--dry-run` — Preview what would be created without modifying files or syncing to GitHub (optional, must be first argument)
- `--workflow issue|epic|blitz|task` — Select the workflow explicitly. Use
  `blitz` for a substantial document-led plan that refinement will link to
  one execution strategy document. Use `task` here for fully scaffolded floor
  intake, or file one complete laneless instruction with `yoke task TITLE
  INSTRUCTION --execution-instructions-considered`. Dash work enters through
  `/yoke dash`; choose it when work needs a git lane or optional gate.
- `{title}` — Short title for the item (required)

## Philosophy

**Maximalist body quality.** Every item body should be a perfect cold-start context for the PM agent that reads it next. Include concrete examples of the problem, verified code references (file paths, function names), observed behavior, and expected behavior. A title-only work item with no body forces the PM to re-investigate from scratch — wasting an entire agent session (P-2, P-48).

**File work items for root causes.** When the operator describes a failure, investigate before filing. Query the events table (`yoke events tail --limit 20`) for recent telemetry. Frame the work item as what could have PREVENTED the failure — missing guardrails, insufficient dispatch context, file too large for agent to read (P-50), missing code-level enforcement (P-26) — not "the agent made a mistake."

**No such thing as "agent error."** Frame every observed failure as a systemic root cause (truncated context, missing instructions, stale references, corrupted input), not as an agent mistake. The full rule — surfaces it covers, banned phrases, and the systemic-framing pattern — lives in `AGENTS.md`'s `## Code Conventions` section. This SKILL does not restate it.

**Artifact writes are work writes.** Work item/spec/body/File Budget/path-claim/GitHub issue-body edits authored by idea are shared coordination state — same ownership invariant as code edits. Hold the work claim on the item before mutating any of those surfaces. Session ids returned by `who-claims` are coordination identifiers, not authority to mutate as that holder; copying a holder session id into another session does not grant capability over that holder's claim.

## Phase map — read one file, at the phase it governs

| Phase | You are here when | Read before acting |
|---|---|---|
| 1. Validate the title | `/yoke idea` was just invoked | this file |
| 2. Infer and create | The title fits the project's effective limit | [`infer-and-create.md`](infer-and-create.md) |
| 3. Body and sync | The item row exists | [`body-and-sync.md`](body-and-sync.md) |
| 4. Path closure | The body is persisted and verified | [`path-closure.md`](path-closure.md) |
| — Claim overlap surfaced | Registration conflicts with another item's active claim | [`path-claim-blocking.md`](path-claim-blocking.md) |
| — Invocation caveats | You need the CLI-vs-skill boundary, the question budget, or the per-workflow handoff | [`notes.md`](notes.md) |

## Steps

Stamp the session mode so the board's active-session row reflects the live phase (default `wait` misrepresents an active idea). Use the registered session wrapper:

```bash
yoke sessions touch --mode idea
```

1. **Validate the title.** If no title was provided, ask for one. Read the target
 project's effective limit from `yoke workflows definition get --project PROJECT`
 (`title_max_length`); if the title is longer, ask the user to shorten it and move
 detail into the body. Do not proceed until the title fits that limit.

2. **Read [infer-and-create.md](infer-and-create.md) and [body-and-sync.md](body-and-sync.md) in parallel**, then execute them in order.
 - infer-and-create: metadata inference, cross-project hard blocks, duplicate detection, item creation, dependency persistence, and the creation confirmation.
 - body-and-sync: mandatory body persistence, additive-only body handling, AC normalization, effective File Budget/path-claim posture resolution, conditional **File Budget seeding** (the upstream counterpart to the universal 350-line file cap — see body-and-sync.md "File Budget" section), body-write verification, and GitHub body sync.

3. **Close the enabled path axes.** Read
 [`path-closure.md`](path-closure.md) and follow it. Claim overlap does NOT
 narrow scope; that file carries the rule and routes conflicts to
 [`path-claim-blocking.md`](path-claim-blocking.md).
