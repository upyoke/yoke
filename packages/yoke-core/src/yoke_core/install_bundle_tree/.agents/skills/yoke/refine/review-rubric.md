# /yoke refine — Review Rubric

Extracted from `SKILL.md`. Contains step 5 (critique) — detailed dimensions, quality gates, and scoring criteria.

---

### 5. Critique

Before writing any changes, complete these mandatory checks and carry the findings into the critique. **Incorporate all survey findings from step 3** — staleness, overlap with active/pipeline/done tickets, and codebase drift from recent commits are first-class critique dimensions, not sidebar observations.

- **Approved decisions inventory (mandatory first check):** Before any other critique, identify every concrete structural decision already present in the spec: directory trees, file layouts, "X stays at Y" / "X moves to Y" statements, specific naming choices, interface shapes, and concrete ACs about where things go. List them explicitly in the critique under a "Decisions to preserve" heading. These are the operator's approved intent and must survive refinement intact. If the spec contains a directory tree diagram, that tree is the canonical layout — do not abstract it away.
- **User-provided input inventory (mandatory first check):** Scan the spec for user-voiced content: numbered questions or items from the operator, "I noticed/saw/found" observations, screenshot references, direct quotes, evidence links, "why does X" / "what's the point of" phrasing, and any content that reads as the operator's own words rather than agent-generated prose. List them explicitly in the critique under a "User questions and evidence to preserve" heading. These items must appear verbatim in the enhanced spec — they define what the ticket must answer or address.
- **Staleness and overlap (from step 3):** If the survey found codebase drift, overlapping tickets, or recently-done work that affects this item, those findings MUST appear in the critique. Recommend descoping, absorbing, dependency-linking, or cancellation as appropriate.
- **Events forensics:** Query item-specific events with `yoke events query --item {N}` when available; otherwise inspect recent telemetry with `yoke events tail --limit 20`. Use that context to decide whether the artifact quality problem reflects a systemic dispatch/context issue.
- **Reference verification:** For every concrete file path, function name, script name, config key, or column named in the artifact, verify it against the live codebase before trusting or rewriting it.
- **Codebase-reader naming:** Assume future readers of the codebase will NOT have the ephemeral planning artifacts this item was written from. For every proposed new or renamed file, module, helper, test, doc, command, event, config key, symbol, heading, or comment, verify that the name describes current function, purpose, mechanics, or domain role to a repository reader. Flag and rewrite names derived from tickets, strategy docs, plan names, initiatives, phases, task/thread numbers, AC/FR identifiers, branches, worktrees, or implementation batches unless that identifier is itself a runtime/domain concept.
- **Blast radius discovery:** If the artifact renames, removes, replaces, or broadly changes behavior, add grep/search-based discovery guidance and residue checks instead of relying on remembered file lists.
- **Cleanup coverage:** If the artifact replaces or removes behavior, explicitly identify dead code, dead docs, dead tests, dead config, compatibility shims, and migration residue that should be deleted.
- **Failure/recovery coverage:** If the artifact describes a state-changing or write path, ensure it names failure modes, partial-state behavior, and operator recovery/rollback expectations.
- **Open-question closure:** For issue-scoped artifacts, resolve open questions or assign explicit defaults whenever the answer would change interfaces, files touched, data model, or user-visible behavior.
- **Prompt/file-size awareness:** If the artifact itself is a large prompt/doc/script surface, note any P-50 risk or line-count pressure in the critique so downstream work does not inherit an unreadable blob.
- **Simplify lenses (reuse / quality / efficiency):** Apply the simplify three-axis vocabulary from `AGENTS.md`'s `## Simplify — three-axis doctrine` section to the spec/plan as feedforward critique. These are first-class rubric items, not advisory afterthoughts.
  - **reuse lens (required):** Does the spec/plan name the existing helpers, templates, skills, modules, events, and command surfaces it will use? An empty reuse section is valid only with an explicit "no relevant existing surface" justification — write that justification verbatim if no existing surface applies. Flag any spec that proposes a new file/helper/skill/event/command without first naming what was searched and why nothing existing fits.
  - **quality lens (required):** Is the plan capped at the minimum surface that satisfies the ACs? Are explicit out-of-scope boundaries declared? Flag scope creep, parameter sprawl, copy-paste-with-variation, leaky abstractions, and unnecessary indirection. The refined spec must include explicit out-of-scope boundaries when the request invites scope creep.
  - **efficiency lens (required):** Does the plan justify any proposed new table, event, skill, config value, command, or prompt surface against existing ones? Flag speculative transitional work ("do X so maybe later we can do Y" when Y is not committed). At planning time, efficiency means asking whether existing infrastructure can be extended before adding a new surface.
- **Future-concept pull-forward lens:** If the item adds or changes `actor_id`, `session_id`, `heartbeat_at`, ownership, leases, claims, approvals, overrides, evidence, run records, execution journals, compiled packets, route-around facts, resource locks, or shared-state coordination, decide whether that surface is the smallest honest v0 of a later end-state primitive. If yes, the refined spec must name the primitive, current consumers, and explicit out-of-scope future surface. If no, the spec must name the deletion or absorption target. Flag any plan that creates a local temporary surface while an existing primitive (`path_claims`, `coordination_leases`, events, actors, phase runs, execution journal, compiled packets) can be consumed instead.
- **File Budget (required for implementation-bearing items):** A first-class readiness check, not advisory. The hard limit is 350 lines per authored file (owned by `yoke_core.domain.file_line_check`); the design target is `<=300` lines so implementors have editing headroom. Refine treats missing or vague File Budget as a critique-and-fix item, the same way it treats missing acceptance criteria.
  - **Issue idea refinement.** If the ticket is implementation-bearing and the body has no `## File Budget` section, **add one** as part of the same refinement pass — list likely files/modules with single responsibilities. If the file shape is genuinely unknown, either resolve it through investigation (read the surfaces the ticket would touch, verify line counts with `wc -l`) or escalate per `update-protocol.md`'s File Budget escalation rule. If a proposed file already owns multiple responsibilities and is likely to exceed the budget, **split the expected implementation shape** before advancing. If the ticket is genuinely non-code, record `N/A` plus a one-line reason — do not advance an implementation-bearing ticket with a fake `N/A`.
  - **Epic plan refinement.** Every epic task that creates or grows authored code must carry a task-level file budget. Worktree plans must not hand a single task an obvious oversized module responsibility (a task that names a single file expected to land >300 lines is a planning failure, not an implementation failure). Plan refinement must flag missing or vague task-level file budgets before advancing to `planned`.
  - **Surfacing file-size pressure.** When a touched source file is already at 300+ lines, name it explicitly in the critique under the File Budget heading. The most common collision points are large agent prompts (`runtime/agents/engineer.md`, `runtime/agents/tester.md`), large skill files, and shared domain modules — splitting them before adding new content is cheaper than splitting them mid-implementation.
- **DB claim consistency:** If the spec, technical plan,
  or any structured field names governed DB mutation — `ALTER TABLE`,
  `INSERT INTO <governed table>`, `migration_audit`, `governed
  migration`, `authoritative DB`, schema changes, backfill, bulk data —
  the stored `db_mutation_profile` must either be `state="declared"`
  with the matching attestation OR carry an explicit reviewed-none
  decision recorded through the amendment workflow. Read the current
  claim via the `items.get.run` function call (`fields:
  ["db_mutation_profile"]`); if it is `{"state":"none"}` while the
  prose declares DB work, surface this as a first-class critique item
  and dispatch `db_claim.amend` (target `{kind: "item", item_id: N}`)
  with `payload = {reason: "<why>", claim: <unified-claim-json>}`
  before advancing. **Meta-tickets about DB governance** — tickets that
  *discuss* `ALTER TABLE`, `ADD COLUMN`, `migration_audit`, or similar
  terms while themselves performing no governed mutation — dispatch
  `db_claim.amend` with `payload = {reason: "<why the ticket does not
  mutate the governed DB>", claim: {state: "none"}}` instead of a
  declared payload. That amendment records a reviewed-none decision in
  the `DbClaimAmended` event stream; the prose-vs-claim gate honors
  that signal and clears even structural DDL-shape hits. Do **not**
  teach or recommend backtick-wrapping DDL verbs or scrubbing
  governance vocabulary from the spec as a workaround — those are not
  the canonical remediation. The structured-write gate
  (`GATE_DB_CLAIM_PROSE_MISMATCH`) blocks advancement when prose and
  stored claim diverge without reviewed-none evidence, so unblocking is
  mandatory. The unified payload demultiplexes into both the
  `db_mutation_profile` and `db_compatibility_attestation` columns atomically;
  no raw JSON edits.

Evaluate each non-empty artifact against these dimensions:

**Body / Spec**
- Problem statement: Is it clear what problem this solves and why it matters?
- Scope: Are boundaries explicit? Are non-goals stated?
- End-to-end completeness: Can the operator actually use and experience the result after this ticket ships? If the spec describes building a feature but doesn't mention wiring it into the UI, CLI, or workflow where users encounter it, that's a gap. If it changes behavior but doesn't mention updating the docs/help text/error messages that describe that behavior, that's a gap. Trace the user's journey from trigger to outcome and flag every missing step.
- Missing requirements: Would a reasonable person expect outcomes that the ticket doesn't mention? Surface them aggressively — error handling, input validation, user-facing messaging, edge cases obvious from the problem statement, integration points with existing systems. The question is not "did the operator write this down" but "would the operator be surprised if this wasn't done."
- Error and rollback paths: For any state-changing operation (status transitions, deployments, merges, DB mutations), does the spec describe what happens when it fails mid-way? What state is left behind? How does the operator recover? Happy-path-only specs are incomplete specs.
- Blast radius — prefer discovery over lists: Are ALL affected files, configs, docs, tests, scripts, and downstream consumers identified? Critically, the spec should include grep-based discovery commands (e.g., `grep -r OLD_PATTERN .`) rather than hardcoded file lists, because hardcoded lists are inherently incomplete. The spec should say "grep to find ALL consumers" and include the grep command as an AC, not just list the files the author happened to remember.
- Cleanup requirements: Does this ticket replace, remove, or supersede anything? If so, the spec MUST explicitly list what gets deleted: dead code paths, obsoleted utilities, stale migration scripts, orphaned test fixtures, config keys for removed features, compatibility shims that nothing uses, re-exports and aliases for renamed things, defensive error handling for states that can no longer occur, and documentation sections that describe the old way. Partial cleanup — removing the main thing but leaving its support infrastructure — is incomplete scope.
- Migration strategy: If the ticket involves a data or behavioral migration, does it justify the migration complexity? Default assumption should be hard cutover unless there's provably live data/users that need graceful migration. Flag over-engineered migration plans. Flag migration scripts that would operate on data that has already been fully cleaned up.
- Documentation cleanliness: After this ticket, will docs describe the current state as if the old way never existed? Or will they accumulate archaeological layers ("this used to work like X but now works like Y")? Docs should be rewritten to describe the present, not amended with changelog entries.
- Code reference verification: Does the spec reference specific file paths, function names, column names, or line numbers? If so, are they verified against the current codebase, or written from memory? Specs with phantom references (function names that don't exist, incorrect column names, wrong line numbers) waste engineering time. Every code reference should be verifiable via grep/read. Use semantic anchors (function names, unique code patterns) alongside line numbers — line numbers drift, semantic anchors are stable. Format: "function _resolve_status() (currently ~line 305)".
- Codebase-reader naming: Do proposed paths, symbols, headings, comments, tests, commands, events, and config keys describe current function/purpose/mechanics to a repository reader who cannot see this ticket or plan? Rewrite provenance-shaped names from phases, tasks, AC/FR labels, strategy docs, branches, worktrees, or implementation batches before refinement passes.
- Acceptance criteria: Are they present, testable, and unambiguous? Do they use canonical `- [ ] AC-N: {description}` format? Are there common-sense ACs that should exist but don't? Every dimension above (end-to-end, blast radius, cleanup, documentation, error paths) should have corresponding ACs if the gap is non-trivial. For rename/removal tasks, include a residue-grep AC: `grep -r OLD_PATTERN . should return 0 results`.
- Migration retire-AC topology match: When the item's DB claim declares `mutation_intent='apply'` (see the `db_mutation_profile` JSON-nested-field schema in your packet) and the profile carries one or more `migration_modules`, the spec must include a retire-the-module AC whose timing matches the project's install topology (per `AGENTS.md` `## Cutover-ticket AC wording`). Resolve via `yoke_core.domain.migration_install_topology.project_model_is_single_install(conn, project, model_name)`. Single-install models: AC says *"deleted in the same slice as live-apply, once the migration audit row reports `state='completed'` on the model's authoritative DB."* Multi-install models: AC says *"deleted in the same commit range after the migration audit row reports `state='completed'` on every install."* Reject any retire-AC that says only "after it has run" (validation-surface ambiguity), or that uses the multi-install wording for a single-install project (delays cleanup unnecessarily), or that uses the single-install wording for a multi-install project (premature cleanup before fan-out completion). Replace the offending AC with the canonical wording — operators no longer hand-author the timing clause.
- Dependencies: Are upstream and downstream dependencies noted?
- Likely files: Are affected files identified? This includes implementation files AND test files (look for test-{module}.sh patterns), documentation, configs, scripts, and any file that references the behavior being changed or removed. Prefer grep-based discovery over manual enumeration.
- Sizing check: Does the scope match the item type? If the spec has 5+ FRs touching 3+ files in different subsystems, it should probably be an epic, not an issue. If it has 7+ FRs or 10+ ACs, flag it as likely needing task decomposition.
- Self-consistency: Do all sections of the spec agree with each other? Check: FRs must not contradict non-goals. Narrative/prose sections must reflect the final formal requirements (early narrative written before requirements were refined is a common source of contradictions). If open questions were resolved, the resolution must be propagated to ALL sections that referenced the original assumption. AC counts should match FR counts. Flag any internal contradictions.

**Design spec**
- UX flows: Are user interactions described step by step? Can the user complete the full journey, or does the flow stop at an implementation boundary?
- Edge cases: Are error states, empty states, and boundary conditions covered?
- Cleanup: If the design replaces an existing flow, does it specify removing the old flow's artifacts (UI components, routes, help text, screenshots)?

**Technical plan / worktree plan**
- Task decomposition: Are tasks scoped to a single session or reviewable unit? Sizing heuristic: if implementation + tests fit in one file or two closely related files and total under ~50 lines of change, keep them in one task. Never create empty-body tasks.
- Interface contracts: Are boundaries between tasks explicit? Contracts MUST include full function/method signatures with parameter names and types, all field names and types for data models, and the exact output format with a concrete example. "Exports: ErrorResponse model" is insufficient; "Exports: ErrorResponse(error: str, detail: str, status_code: int)" is required.
- Code reference verification: Does the plan reference specific files, functions, columns, or line numbers? Are they verified against the live codebase? Plans written from memory or cached investigation are a leading cause of wasted engineering time. Every file path should exist, every function name should be grep-verifiable, every column should match the live schema.
- Risks: Are known risks and mitigations called out?
- Epic alignment: If epic tasks already exist, do they still match the plan and worktree grouping?
- Concurrent modifications: Does the plan check for other in-flight items that modify the same files? If overlap exists, the plan should document the overlap and merge strategy.
- Cleanup tasks: Is there an explicit task (or explicit coverage within tasks) for removing obsoleted code, tests, docs, config, and migration scripts? If the plan only adds and modifies but never deletes, that's suspicious.
- Migration simplicity: Does the plan default to hard cutover? If it proposes graceful migration, is there evidence that graceful migration is actually needed (live data, live users, active integrations)? Flag plans that build migration scaffolding for data that doesn't exist or has already been cleaned up.
- Efficiency and simplification: Does the plan propose unnecessary indirection, over-abstraction, or roundabout approaches where a direct solution exists? Flag wrapper functions that just pass through, abstraction layers with a single consumer, multi-step pipelines that could be a single operation, and plans that introduce new infrastructure when existing infrastructure already handles the case. The simplest correct approach should be the default.
- Durable naming: When the plan creates or renames live codebase surfaces, do task ACs name the functional surface to use? Reject plan names copied from planning artifacts; the implementation vocabulary must stand alone to future repository readers.

**Browser QA Metadata**
- Read the current object with `yoke items get YOK-{N} browser_qa_metadata`. If empty or `null`, flag a regression — every item should carry at least the explicit negative-default object after creation.
- Is `browser_testable` consistent with the spec? Tickets that ship code affecting what a user sees in a browser should be `true`; backend-only, CLI-only, or infrastructure items should be `false`. `visual_outcome=true` requires `browser_testable=true` — the validator rejects the contradiction.
- Do `browser_routes` match the routes the spec actually covers? Surface routes the spec names but metadata misses, and surface metadata entries that reference prose words (`settings`, `account`, `dashboard`) in non-URL contexts. Negative-path: if a route is only mentioned in a code-block or as a doc path, it should NOT appear in metadata.
- Do `browser_timing_hints_ms` reflect AC language like "visible 7 seconds after load" or "fades in within 1500 ms"? Never pad with a floor — the browser QA executor applies the 2000 ms settle-delay floor.
- When metadata is wrong, mark it as a first-class critique item (not
  a sidebar observation) and propose the correction via the
  `items.structured_field.replace` function call (`target = {kind:
  "item", item_id: N}`, `payload = {field: "browser_qa_metadata",
  content: "<corrected-json>", source: "refine"}`). The validator at
  `yoke_core.domain.browser_qa_metadata.validate_json_string` runs
  inside the handler, so a malformed or contradictory correction is
  rejected before persistence. Correction writes are structurally
  equivalent to other structured-field writes — additive-only
  discipline applies: correct wrong facts, do not silently abstract
  away routes or timings the prior pass captured deliberately.
- If the operator has since added new routes, new timing language, or flipped visibility expectations in the spec, the metadata write is how refine records that understanding — do not leave it to the advance-time browser seeding gate to rediscover.

**Shepherd caveats**
- Open question resolution: For issue-scoped items (single-session work), ALL open questions MUST be resolved or given explicit default answers before the item reaches its execution-ready handoff state. Heuristic: if resolving an open question would change the number of files touched or the data model, it is a spec decision that MUST be resolved. If it only changes task ordering, it can be deferred. FRs must never reference unresolved open questions as firm requirements.
- Are deferred items captured with YOK-N references?
- Are any "deferred to future ticket" items actually common-sense requirements that belong in THIS ticket? Challenge deferrals that would leave the feature incomplete from the operator's perspective.

Emit a structured critique:

```
## Refinement Critique — YOK-{N}

### Strengths
- {what is already good}

### Issues Found
1. {issue}: {description}
2. ...

### Recommended Changes
1. {change}: {what to write and where}
2. ...
```
