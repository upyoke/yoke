# Active — Implementation Guidance

The same session holds the item claim and registered WORKTREE_PATH.
Use [project context](project-context.md) before discovery and
[test/record](test-and-record.md) for the authoritative verification roster.

## Discover, edit and simplify

Start with concrete implementation/test paths and patterns actually surfaced
from project docs. Known filenames/symbols use narrow Read/rg; large known
files use relevant ranges. Exclude git, worktrees, caches, build and vendored
output. Broad exploration is only for unknown areas, with explicit scope
and depth. Reuse a verified repeated pattern rather than re-exploring it.

If an edit misses its target, file the immediate field-note, then reread.
Do not retry identical stale text. Move on only when the intended state is
verified; otherwise correct the actual gap or escalate.
For bulk edits use a unique minimal pattern, grouped variations and a residue
search. Avoid fragile giant context replacements.

Apply AGENTS.md's Simplify — three-axis doctrine: name relevant reuse,
smallest AC-satisfying shape, extension-vs-create justification and future
concepts around shared authority, leases, claims, evidence and approvals.
Apply codebase-reader naming before every first write: names/headings explain
current function, purpose, mechanics or domain to a reader without the planning artifacts.
No planning/work-item/AC/phase/branch provenance unless runtime-domain data.

## DB discovery: stop and amend

If implementation discovers schema, migration, bulk authoritative mutation
or migration_audit writes, stop coding and inspect
`yoke items get PREFIX-N db_mutation_profile`.
Correct a negative or incomplete claim through registered `db_claim.amend`
before continuing. The unified claim atomically stores profile/attestation;
pre_merge_safe needs readers/writers, invariants, rehearsal commands and
residual risk inline. See the
[DB function home](../../../../../.yoke/docs/reference/db-reference/functions-claims.md)
for the live payload. No rollback to idea is required.
Review checks prose-vs-claim and rehearsal evidence; an event is telemetry,
not a replacement for stored claim authority. Permanent migration history
and both exception apply surfaces remain required.

## Continuity and independent checks

Use the item's Progress Log for multi-turn current state, blockers and next
action. Never put checkpoints in spec intent or task-graph planning fields.
The item is the plan; keep a small progress checklist only when helpful.

Independent targeted checks may run concurrently only with separate temp/DB/
port/output state and wrapper admission. Shared state or network resources
require ordering. Do not bypass machine-wide local-suite admission or duplicate
full execution; test/record owns the runner.

## End-of-Implementation Chain Directive

Implement reaches its binding's handoff, not “tests pass”.
Record real AC proof, commit review fixes, refresh affected QA and use the
pinned adjacent lifecycle writes through [review](../review.md).
Release only after the handoff succeeds. A real blocker names evidence and
checkpointed recovery.

<!-- Keep Implementation Re-Anchor LAST in this implementation flow. -->
## Implementation Re-Anchor

**Do NOT end your turn. Begin implementation NOW.** Your next action is a tool call.

0. **`cd "{WORKTREE_PATH}"`** is the sticky-cwd anchor.
   Static-cwd tools inline absolute lane paths and `git -C`; tests must
   collect from the claimed lane, not main. Source-dev commands use
   `yoke dev run -- <command>` where the project requires it.
1. Read `yoke items get PREFIX-N spec`; if empty, read body.
2. Read effective File Budget and path-claim policies independently.
   When budget is enabled, obey its full planned-file sizing; when off,
   derive required scope from spec without inventing a budget.
   Universal 350 authored lines, design target <=300, and the
   `yoke_core.domain.file_line_check` backstop apply in every posture.
   Widen every required new/sibling path before editing.
3. Use the immutable plan cases and declared test commands from test/record.
4. Text-sensitive preflight must already have run; run it now if missing
   before the first edit, and blocking verify before each relevant commit.
5. Apply Simplify and codebase-reader naming before authoring.
6. Begin the spec's implementation entirely in this registered lane.
7. Maintain current-state Progress Log through long sessions and continue
   QA/review to the fresh binding handoff, with no menu or premature DONE.
