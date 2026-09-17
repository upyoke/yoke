---
name: dash
description: "File or execute instruction-led Dash work through survey, isolation, verification, merge, and evidence."
argument-hint: "\"instruction\" | {PREFIX-N}"
---

# /yoke dash

Execute one instruction directly, end to end: implementation, verification,
merge, and delivery in this session. Dash is defined by that execution
structure, not by size — it carries a one-line correction and a very large
change alike. A new instruction is filed and executed immediately; an item
reference resumes an existing Dash. Dash uses ordinary item, claim, worktree,
lifecycle, QA, merge, and deployment surfaces.
It does not route through `/yoke idea`.

`/yoke dash "instruction"` files and executes. `/yoke dash PREFIX-N` (or a bare
number, resolved against the current project's sequence) resumes.
`yoke dash "title" "instruction" --execution-instructions-considered` files
without executing; `yoke task ...` is the laneless, merge-free alternative with
no optional gate posture.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Phase map — read one file, at the phase it governs

Read the phase you are entering. Do not pre-read the whole set; each file ends
by naming the next one.

| Phase | You are here when | Read before acting |
|---|---|---|
| 1. Resolve or file | The argument just arrived | [`file-and-claim.md`](file-and-claim.md) |
| 2–3. Survey and isolate | `ITEM` is claimed and read | [`survey-and-isolate.md`](survey-and-isolate.md) |
| 4. Execute | The lane exists and the item is `implementing` | [`implement.md`](implement.md) |
| 5. Verify | The change is written | [`verify.md`](verify.md) |
| 6. Merge | The item reached `reviewing-implementation` | [`merge.md`](merge.md) |
| 7. Close out | The merge landed, or the result is laneless | [`close-out.md`](close-out.md) |
| — Escalate | A decision boundary appeared at any phase | [`escalate.md`](escalate.md) |
| — Look up a function id | You need an operation's exact envelope or adapter | [`function-reference.md`](function-reference.md) |

## Invariants — these bind at every phase

- Treat the stored instruction as the complete requested scope.
- Obey the `# Workflow Execution Instructions` operator block at the top of
  fetched item content; it layers on top of, and never replaces, the item's own
  stored instruction and spec.
- Acquire the item work claim as the first action once the item reference
  exists, and hold it through the Dash. Release is conditional on what close-out
  already did.
- Perform all writes in the registered item worktree, never in main.
- Survey contacts are advisories: proceed or yield after reading each one.
- Size is not a reason to leave Dash, and a larger-than-expected touch set is
  not a decision boundary. Do not create child items. Raise a different
  workflow only for a concrete structural need — parallel worktrees or a
  generated task graph — or when the operator asks; escalation cancels the
  Dash, so halt and discuss it first.
- Consume the central `workflows.item.get` effective-policy projection before
  authoring or gating File Budget and path claims. Each axis remains
  independent; do not reconstruct it from raw policies or posture.
- Honor every selected item-posture knob. Posture can tighten execution; it
  cannot remove a workflow gate or a governed migration invariant.
- Do not transition to `done` until the branch is merged and the evidence
  record contains the result, passing verification, merge identity, and touched
  files, and every selected posture passes its real authority gate.

## Start

Stamp the session mode first, so the board's active-session row reflects the
live phase (the default `wait` misrepresents an active Dash):

```text
yoke sessions touch --mode dash
```

Then read [`file-and-claim.md`](file-and-claim.md) and follow it.
