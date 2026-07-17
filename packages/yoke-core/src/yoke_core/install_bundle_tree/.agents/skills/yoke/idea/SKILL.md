---
name: idea
description: Create a new backlog item with a YOK-N ID. Infers project, type, priority, and flow from context.
argument-hint: "{title}"
---

# /yoke idea [--dry-run] {title}

Create a new backlog item and assign it the next available YOK-N ID.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug not worth a ticket, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Arguments

- `--dry-run` — Preview what would be created without modifying files or syncing to GitHub (optional, must be first argument)
- `{title}` — Short title for the item (required)

## Philosophy

**Maximalist body quality.** Every item body should be a perfect cold-start context for the PM agent that reads it next. Include concrete examples of the problem, verified code references (file paths, function names), observed behavior, and expected behavior. A title-only ticket with no body forces the PM to re-investigate from scratch — wasting an entire agent session (P-2, P-48).

**File tickets for root causes.** When the operator describes a failure, investigate before filing. Query the events table (`yoke events tail --limit 20`) for recent telemetry. Frame the ticket as what could have PREVENTED the failure — missing guardrails, insufficient dispatch context, file too large for agent to read (P-50), missing code-level enforcement (P-26) — not "the agent made a mistake."

**No such thing as "agent error."** Frame every observed failure as a systemic root cause (truncated context, missing instructions, stale references, corrupted input), not as an agent mistake. The full rule — surfaces it covers, banned phrases, and the systemic-framing pattern — lives in `AGENTS.md`'s `## Code Conventions` section. This SKILL does not restate it.

**Artifact writes are work writes.** Ticket/spec/body/File Budget/path-claim/GitHub issue-body edits authored by idea are shared coordination state — same ownership invariant as code edits. Hold the work claim on the item before mutating any of those surfaces. Session ids returned by `who-claims` are coordination identifiers, not authority to mutate as that holder; copying a holder session id into another session does not grant capability over that holder's claim.

## Steps

Stamp the session mode so the board's active-session row reflects the live phase (default `wait` misrepresents an active idea). Use the registered session wrapper:

```bash
yoke sessions touch --mode idea
```

1. **Validate the title.** If no title was provided, ask for one. If it exceeds 100 characters, ask the user to shorten it and move detail into the body. Do not proceed until the title is `<=100` characters.

2. **Read [infer-and-create.md](infer-and-create.md) and [body-and-sync.md](body-and-sync.md) in parallel**, then execute them in order.
 - infer-and-create: metadata inference, cross-project hard blocks, duplicate detection, item creation, dependency persistence, and the creation confirmation.
 - body-and-sync: mandatory body persistence, additive-only body handling, AC normalization, **File Budget seeding** (the upstream counterpart to the 350-line file cap — see body-and-sync.md "File Budget" section), body-write verification, and GitHub body sync.

3. **Path Closure.** Before idea exits, the File Budget and the path-claim must be complete and consistent. The exit condition:
 - Every file the implementer will edit is enumerated in `## File Budget`, one path per line, with its line allocation. **Counts and approximations are not acceptable** — phrases like "roughly 30 files", "every caller", "all importers", "the survey shows N matches" must be expanded into a literal path list before exit. If you can't list them, the work isn't ready.
 - The path-claim's declared paths cover everything in the File Budget (verified by `yoke readiness check`).
 - Use whatever investigative work the spec demands — grep, sub-agents, codebase reading — to produce the full enumeration. The deliverable is the populated File Budget + matching claim, not a description of the work.
 - **Claim overlap does NOT narrow scope.** If a required file is already covered by another item's active or non-terminal path claim, the file stays in the File Budget and in this item's path-claim attempt. Active path claims are coordination/dependency/blocking facts — never permission to omit a required file. If registration conflicts, surface the conflict and route to the canonical resolution protocol at [`path-claim-blocking.md`](path-claim-blocking.md). The default shape is `coordination_only` (compatibility edge, no lifecycle gate) for independent same-file edits; order-dependent overlaps use directional `activation` instead. The full shape list, the columns they touch, and the resolution order live in `path-claim-blocking.md` and your `path_claims` packet stanza; this SKILL does not restate either surface. See `AGENTS.md` `## Path Claims — Hard Rule` for the full doctrine.

 Do NOT exit path closure with the spec saying "N files implied" while only listing a subset. If the readiness check passes but the spec body still contains "every X" / "all Y" / "~N files" prose without an enumeration alongside it, treat that as a structural defect and resolve it before handing off.

 **Only physical files belong in `## File Budget` list-item backticks.** Function ids (`items.section.upsert`), event names, command surfaces, and other operational references go in surrounding prose — not in the `- ` list-item backticks the parser inspects. The dotted-identifier carve-out in `yoke_core.domain.file_budget_paths` silently drops them, but writing them in the budget at all confuses both reader and future consumer.

## Notes

- **`/yoke idea` is a harness skill entrypoint, not a `yoke` CLI subcommand.** Invoke it as the `/yoke idea` slash command — there is no `yoke idea` CLI adapter, so `yoke idea --help` returns `unknown subcommand`. The `yoke <subcommand>` CLI wraps item/claim/lifecycle operations; ticket *intake* is a skill flow, not a CLI verb.
- Status is always `idea` for new items. Use `/yoke shepherd` to drive the item through the quality-gated lifecycle.
- The YOK-N ID is permanent — it never changes even after GitHub sync.
- Items are auto-synced to GitHub on creation. If GitHub sync is unavailable, the item is created locally and can be synced later through the internal item sync repair path; do not teach that repair path as normal product flow.
- This is a write command — it creates a file and inserts a DB row.
- **Maximum questions rule:** This flow asks at most 3 binary questions total per invocation. Most items should require zero questions (all fields inferred from context). Count your questions — if you have already asked 3, stop asking and use best-guess defaults for remaining ambiguities.
