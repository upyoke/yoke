# /yoke idea — policy-aware path closure

Read this after the item is created and its body is persisted, before
Idea authors or gates the File Budget or path-claim surface.

After creation and before Idea authors or gates either surface, call registered `workflows.item.get` through
`yoke workflows item get ITEM --json`. Consume only
`result.effective_policies.file_budget` and
`result.effective_policies.path_claims` as authority. `required` enables
the item surface, `required_per_task` enables the generated-task surface,
and `optional` is off. Never reconstruct these values from the raw pinned
definition or posture; the runtime owns historical compatibility and
allowed tightening.
- When File Budget is enabled, every file the implementer will edit is
   enumerated in `## File Budget`, one path per line, with its line
   allocation, current line count, remaining headroom against 350, and
   explicit at-or-over-limit flag. **Counts and approximations are not acceptable** — phrases
   like "roughly 30 files", "every caller", "all importers", "the survey
   shows N matches" must be expanded into a literal path list before exit.
- When path claims are enabled, author complete declared coverage. If File
   Budget is also enabled, its paths and claim coverage must agree at the
   applicable item/task scope (verified by `yoke readiness check`). If File
   Budget is off, derive claim paths from the spec's execution scope and
   investigation rather than inventing a budget.
- When File Budget is enabled and path claims are off, keep the budget as
   sizing and conflict-survey evidence; do not register a claim merely to
   mirror it.
- When both axes are off, neither artifact is required. The universal
   350-line authored-file limit still applies through
   `yoke_core.domain.file_line_check`.
- For an Epic whose effective path-claims value is `required_per_task`, intake is the
   exception: keep the full parent File Budget, but defer claim registration
   until Shepherd persists generated tasks and `epic_task_files`. Never mint
   an unbound parent claim as a substitute; the required gate reports this
   pre-task state as a deliberate deferral.
- Use whatever investigative work the spec demands — grep, sub-agents,
   codebase reading — to produce the full derived touch set. Materialize that
   set in whichever axes are enabled; when both are enabled, the deliverable
   is the populated File Budget plus matching claim.
- **Claim overlap does NOT narrow scope.** If a required file is already covered by another item's active or non-terminal path claim, it stays in the execution artifact; when File Budget is enabled, the file stays in the File Budget, and when claims are enabled it stays in the claim surface. Active path claims are coordination/dependency/blocking facts — never permission to omit a required file. If registration conflicts, surface the conflict and route to the canonical resolution protocol at [`path-claim-blocking.md`](path-claim-blocking.md). The default shape is `coordination_only` (compatibility edge, no lifecycle gate) for independent same-file edits; order-dependent overlaps use directional `activation` instead. The full shape list, the columns they touch, and the resolution order live in `path-claim-blocking.md` and your `path_claims` packet stanza; this SKILL does not restate either surface. See `AGENTS.md` `## Path Claims — Hard Rule` for the full doctrine.

Do NOT exit path closure with the spec saying "N files implied" while only listing a subset. If the readiness check passes but the spec body still contains "every X" / "all Y" / "~N files" prose without an enumeration alongside it, treat that as a structural defect and resolve it before handing off.

When File Budget is enabled, **only physical files belong in `## File
Budget` list-item backticks.** Function ids (`items.section.upsert`), event
names, command surfaces, and other operational references go in surrounding
prose — not in the `- ` list-item backticks the parser inspects. The
dotted-identifier carve-out in `yoke_core.domain.file_budget_paths` silently
drops them, but writing them in the budget at all confuses both reader and
future consumer.

