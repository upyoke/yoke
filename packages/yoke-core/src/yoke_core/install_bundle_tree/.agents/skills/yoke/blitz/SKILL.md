---
name: blitz
description: "Execute a substantial document-led Blitz as integrated slices with continuous plan evidence."
argument-hint: "{PREFIX-N}"
---

# /yoke blitz {PREFIX-N}

Execute one refined Blitz directly from its single linked strategy
document. The document remains the live plan, progress log, handoff
surface, completion record, and parent-reconciliation record. The item
supplies identity, ownership, lifecycle, claims, worktrees, QA, and
delivery associations.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Phase map — read one file, at the phase it governs

| Phase | You are here when | Read before acting |
|---|---|---|
| 1–3. Read, survey, isolate | `/yoke blitz PREFIX-N` was just invoked | [`read-and-survey.md`](read-and-survey.md) |
| 4–5. Map and execute slices | The lane is active and the item is `implementing` | [`integrate.md`](integrate.md) |
| 6–7. Review and complete | Every slice is integrated | [`review-and-complete.md`](review-and-complete.md) |
| — Look up a function id | You need a Blitz operation's exact envelope | [`function-reference.md`](function-reference.md) |

## Input and invariants

- `{PREFIX-N}` must resolve to a Blitz at `refined-idea`, `implementing`, or
  `reviewing-implementation`.
- Exactly one execution strategy document must already be linked by the
  refine flow. Do not copy it into an item body or generate child items.
- The item claim owns execution. The item-owned document claim owns plan
  revision. Other sessions may use only the append-only `Slice Log` and
  `Live Status` coordination surface.
- The default Blitz has File Budget and path claims off. It still obeys the
  universal 350-line authored-file limit, surveys before activation and every
  slice merge, judges each survey contact (proceed or yield), and runs every
  write in a registered isolated worktree.
- Keep the survey in step 2 minimal: enough to name candidate paths from the
  document's affected areas, not to read them end to end. Prepare and
  activate the worktree (step 3) immediately afterward, before any deeper
  reading or edit.
- The main session owns slice boundaries, integration order, full
  verification, document completion, and parent reconciliation.
- Core invariants run on every action. A continuous delivery model never
  bypasses migration, capability, security, approval, or run-record rules.


## Start

Read [`read-and-survey.md`](read-and-survey.md) and follow it.
