---
name: refine
description: "Read item artifacts, critique them, and write improved work item artifacts back through sanctioned Yoke update surfaces."
argument-hint: "{PREFIX-N}"
---

# /yoke refine {PREFIX-N}

Standalone capability for refining backlog item artifacts. Reads the item's structured fields, critiques them for completeness, clarity, and testability, and writes improved content back through sanctioned Yoke update surfaces.

This is an explicit, operator-invoked capability that Codex can execute directly. It does not require `/yoke do`, lane-aware routing, or lifecycle-family ownership wiring.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Arguments

- `{PREFIX-N}` — Backlog item ID. Accepts prefixed IDs, zero-padded prefixed IDs, or bare numeric IDs.

## Modes

Refine always advances status on successful completion, whether invoked directly (e.g., `/yoke refine PREFIX-N`) or via scheduler routing.

### Lifecycle transitions

Resolve the active `refine` segment from the item's immutable workflow pin.
Interpret `executor_bindings` against the ordered `stages` with the runtime's
half-open interval (`from_stage_id <= current < through_stage_id`). This skill
supports the refine executor's three-rung contract: binding source → one
in-progress stage → binding handoff. Use those served stage ids for entry,
re-entry, and completion; never select a branch from a literal workflow id.

If refine fails or is interrupted, the item must not advance past its current
served stage.

## Constraints

- No worktree required.
- No code edits or commits.
- A Blitz must leave Refine with exactly one verified execution strategy
  document linked through `strategy.execution.link`. Refine links metadata
  only; `/yoke blitz` owns atomic document-claim acquisition and execution.
- Artifact writes are work writes: work item/spec/body sections, File Budget, path-claim register/widen/narrow/release, and GitHub issue-body edits are shared coordination state; hold the item claim before mutating them, and treat `who-claims` session ids as identifiers, not authority.
- Full-field rewrites go through the `items.structured_field.replace`
  function call; additive transforms (preserve existing content, append
  a `## heading`-led block) go through
  `items.structured_field.append_addendum` /
  `items.structured_field.section_upsert` /
  `items.structured_field.section_append`; see
  [`update-protocol.md`](update-protocol.md) step 6 for the full
  surface contract and
  [`../idea/body-and-sync-functions.md`](../idea/body-and-sync-functions.md)
  for the envelope shape.
- Both standalone and routed modes advance status on successful completion.

## QA Preparation

Refine does not derive QA requirements from an item's selected workflow or
Browser posture. Project-default and item-attached plans materialize at their
declared lifecycle transitions. Add an explicit item-specific requirement through
`qa.requirement.add` only when the refined verification contract calls for
coverage outside those attached plans.

## Philosophy

### Cardinal Rule: Never subtract, only add

Refine enhances artifacts by adding what's missing — it never removes, replaces, or paraphrases existing content. The operator's words, questions, evidence, decisions, and ACs are input constraints, not rough drafts to be polished. You may add sections, add ACs, add verification commands, add blast-radius analysis, add scope boundaries, and add cross-references. You may improve wording **in place** (grammar, clarity) without changing meaning. You may NOT delete content, abstract specifics into generalities, paraphrase user questions into scope language, or replace concrete statements with vague ones.

Every rewrite is a lossy transformation. Refine does not rewrite — it enhances in place and appends.

### Escalate, don't correct

If the spec contains a major error — wrong file references, contradictory requirements, a fundamentally flawed approach, scope that conflicts with existing work — do NOT silently fix it. **Stop and surface the issue to the operator.** The operator may have context you don't. Refine is not authorized to make judgment calls about what the operator "really meant" when the spec contradicts reality. Do NOT advance status. Leave the item at `REFINE_ACTIVE_STATUS` and report what you found.

### Corollaries (reinforcing the cardinal rule)

**Concrete decisions are sacred.** If the spec already contains concrete structural decisions — directory trees, file layouts, explicit "X stays at Y" / "X moves to Y" statements, specific naming choices, architectural diagrams, or interface shapes — those represent decisions the operator already approved. You may add discovery commands around them, add blast-radius analysis, or add supporting ACs — but you may NEVER abstract a concrete decision into vague prose. "`runtime/harness/` subpackage unifies all harness code with claude/ and codex/ subdirs" is a concrete decision. "A single truthful ownership model for harness code" is an abstraction that loses the decision.

**ACs are additive, not replacive.** You may add new ACs, renumber, improve wording, and add verification commands. You may NOT delete or replace the substance of an existing AC. Every concrete AC in the original must have a corresponding concrete AC in the enhanced version.

**User voice is verbatim.** When the spec contains content that is clearly the user's own words — numbered questions, direct observations, screenshots, "I saw X", "why does X", evidence references — that content must be preserved word-for-word. User questions define what the work item must answer; user evidence defines the ground truth the work item must address. Abstracting "what's the point of running CI in parallel with deployments?" into "document the tradeoff" loses the question the work item exists to answer.

### Operating principles

**Maximalist interpretation.** Read every work item as "make this fully work end-to-end so the operator can use and experience the result." A minimal interpretation that leaves obvious end-to-end requirements for a hypothetical future work item is a refinement failure. If a reasonable person would expect it to work, the work item should say so.

**Surface what's missing, not just what's unclear.** Refinement fills in what the operator obviously meant but didn't write. Missing error handling, missing cleanup of replaced state, missing documentation updates, missing blast-radius items. Do not fabricate unrelated scope or redesign the work item's purpose, but do complete the picture of what "done" actually looks like.

**Clean-slate mindset.** If the work item replaces, removes, or supersedes something, the spec must explicitly call out what gets deleted. The codebase after this work item should read as if the old way never existed.

**Simplest migration wins.** Default to hard cutover unless there is provably live data, live users, or live integrations that need graceful migration.

**Future-concept lens.** Generation labels are sequencing hints, not architecture walls. If a work item adds or changes `actor_id`, `session_id`, `heartbeat_at`, ownership, leases, claims, approvals, overrides, evidence, run records, execution journals, compiled packets, route-around facts, resource locks, or shared-state coordination, refine must decide whether this is the smallest honest v0 of a later end-state primitive. If yes, shape the spec around that primitive and the concrete current consumers. If no, require an explicit deletion or absorption target so a local workaround does not become accidental architecture.

**Dead weight has zero tolerance.** If the work item obsoletes code, tests, config keys, feature flags, utility functions, documentation sections, migration scripts, or re-exports, the spec must include their removal.

**Be the giant.** Your refined artifacts are the cold-start context for every downstream agent. Every gap you leave is a gap they'll hit. Do the investigative legwork: verify code references against the live codebase, include grep commands for blast-radius discovery, provide concrete examples.

**No such thing as "agent error."** When the critique reveals a bad artifact, the cause is systemic: insufficient dispatch context, ambiguous instructions, or upstream gaps. Frame every issue as what the SYSTEM should change to prevent it.

**Events table for investigation.** When critiquing artifacts, query the events table for diagnostic context: `yoke events query --item {N}`. Anomaly flags and envelope data reveal whether the artifact was produced under context pressure.

**File work items for root causes.** When refinement surfaces a systemic issue, note the root cause for work item filing.

**Think, don't just check.** The dimensions and rules in this skill are a starting point, not a ceiling. Step back and think about the work item as a whole: What is this work item actually trying to achieve? What would a thoughtful senior engineer expect "done" to look like? The checklist catches known failure modes; your judgment catches everything else.

## Steps

### 1. Parse And Lookup

Read and follow [`workflow-context.md`](workflow-context.md). It resolves the
exact pin and exports `ITEM_*`, `REFINE_SOURCE_STATUS`,
`REFINE_ACTIVE_STATUS`, `REFINE_TARGET_STATUS`, and
`REFINE_ARTIFACT_SCOPE`. Do not continue unless its executor guard passes.

### 1b. Claim and Set Entry Status

The workflow-context interpreter already proved the current stage belongs to
exactly one pinned `refine` binding:

- At `REFINE_SOURCE_STATUS`, transition to `REFINE_ACTIVE_STATUS` before work.
- At `REFINE_ACTIVE_STATUS`, proceed without a status write (re-entry).
- Any other stage was rejected in step 1.

Register the work claim BEFORE the status transition (claim-before-status ordering). The session stamp uses the registered session wrapper. This prevents the scheduler from offering the same item while refine is actively working on it, and ensures the subsequent status mutation passes claim verification:

```bash
# Reuse ITEM_REF and ITEM_NUM from step 1. The items.get dispatcher already
# resolved prefixed, zero-padded, and project-local bare-number input.
# Session touch + claim
yoke sessions touch --mode refine
yoke claims work acquire \
 --item "$ITEM_REF"
```

For `REFINE_ARTIFACT_SCOPE=item_artifact`, run the internal pre-handoff
readiness gate before the entry status mutation. The effective flags resolved
from the immutable pin control its checks: File Budget validation runs only
when `ITEM_FILE_BUDGET_POLICY` is non-`optional`, path-claim required checks run only when
`ITEM_PATH_CLAIMS_POLICY` is non-`optional`, and coverage parity runs only when both are
true. Read and follow
[`readiness-repair.md`](readiness-repair.md) for the full classifier
table (`pass` / `pure_stale_count` auto-fix / `FILE_BUDGET_NOT_IN_CLAIM`
auto-widen / `mixed_stale_count` continuation / `unrecoverable`
terminal block), the routing rationale, exact registered commands, claim
release behavior, and `/yoke do` chain-step contract. Run it only when
`REFINE_ARTIFACT_SCOPE=item_artifact` and
`ITEM_STATUS=REFINE_SOURCE_STATUS`.

Then set the entry status, when needed, via the
`lifecycle.transition.execute`
function call (envelope in
[`../idea/body-and-sync-functions.md`](../idea/body-and-sync-functions.md)):

- At `REFINE_SOURCE_STATUS`, use `payload = {target_status:
  REFINE_ACTIVE_STATUS, source_status: REFINE_SOURCE_STATUS}`.
- At `REFINE_ACTIVE_STATUS`, do not emit a no-op transition.

### 2. Gather Artifacts

Read all available structured fields. Empty fields are normal; refinement should still inspect them and decide whether a light structural improvement is warranted.

```bash
MAIN_ROOT=$(git rev-parse --show-toplevel)
# Reuse ITEM_REF and ITEM_NUM from step 1.
BODY=$(yoke items get "$ITEM_REF" body 2>/dev/null) || true
SPEC=$(yoke items get "$ITEM_REF" spec 2>/dev/null) || true
DESIGN_SPEC=$(yoke items get "$ITEM_REF" design_spec 2>/dev/null) || true
TECHNICAL_PLAN=$(yoke items get "$ITEM_REF" technical_plan 2>/dev/null) || true
WORKTREE_PLAN=$(yoke items get "$ITEM_REF" worktree_plan 2>/dev/null) || true
SHEPHERD_CAVEATS=$(yoke items get "$ITEM_REF" shepherd_caveats 2>/dev/null) || true
```

When `REFINE_ARTIFACT_SCOPE=generated_task_plan`, also inspect the persisted
child decomposition selected by `ITEM_GENERATED_CHILDREN=epic_tasks`:

```bash
MAIN_ROOT=$(git rev-parse --show-toplevel)
EPIC_TASKS=$(yoke epic-tasks list --epic "$ITEM_NUM" 2>/dev/null) || true
```

If all fields are empty or trivial, emit:
> **Advisory:** PREFIX-{N} has minimal content. Consider populating the body first or running `/yoke shepherd PREFIX-{N}` before refining.

Proceed anyway — refinement can still add structure to sparse items.

### 3. Contextual Survey

**This step is critical.** Refinement in isolation produces stale, duplicated, or conflicting artifacts. Before critiquing the item, survey the surrounding landscape to ground the critique in reality.

**Recent commits** — What has actually landed recently? The item's assumptions about current codebase state may be outdated.

```bash
MAIN_ROOT=$(git rev-parse --show-toplevel)
git -C "$MAIN_ROOT" log --oneline -20
```

Scan for commits that touch the same files, functions, or subsystems as this item. If recent work has already addressed part of this item's scope, note it — the spec may need descoping or the item may be partially done.

**Active and pipeline work items** — What else is in flight or queued that overlaps?

```bash
MAIN_ROOT=$(git rev-parse --show-toplevel)
yoke db read --format lines "SELECT id, status, title FROM items WHERE status IN ('implementing','reviewing-implementation','reviewed-implementation','polishing-implementation','refining-idea','refined-idea','planning','refining-plan','planned') ORDER BY id DESC"
```

Look for:
- **Overlap** — another work item targeting the same files, functions, or behavior. Flag it in the critique and ensure the spec acknowledges the overlap or deconflicts.
- **Supersession** — a broader work item that subsumes this one. If so, recommend absorbing or cancelling.
- **Dependencies** — a work item that must land first for this item's assumptions to hold, or vice versa.

**Recently done work items** — What just shipped that might affect this item's assumptions?

```bash
MAIN_ROOT=$(git rev-parse --show-toplevel)
yoke db read --format lines "SELECT id, title FROM items WHERE status='done' ORDER BY id DESC LIMIT 15"
```

Check whether recently completed work has:
- Already solved part of this item's problem (descope needed).
- Changed the codebase in ways that invalidate the item's spec, file references, or approach.
- Created new capabilities that this item should leverage instead of building from scratch.

**Staleness check** — Synthesize findings from the three queries above. An item is stale when:
- Its spec references files, functions, or behaviors that have been renamed, removed, or significantly refactored since the spec was written.
- Its problem statement describes a symptom that has already been fixed.
- Its approach assumes codebase state that no longer exists.
- Its scope overlaps with another active or recently-done work item in any way — same files, same behavior, same problem from a different angle. Any overlap must be resolved: descope, absorb, dependency-link, or cancel.

Carry ALL survey findings into the critique in step 5. Staleness and overlap are first-class refinement issues, not optional observations.

### 4. Choose The Refinement Focus

Pick the field(s) to refine based on the current status and whatever structured content actually exists:

- For `REFINE_ARTIFACT_SCOPE=item_artifact`, focus on `spec` first, then
  `design_spec` if the item already has UX or flow detail.
- When `ITEM_NEXT_EXECUTOR=blitz`, also identify the one strategy document that will remain the
  live execution plan. Apply the document-readiness rubric in
  `review-rubric.md`; do not treat the item body as the execution document.
- For `REFINE_ARTIFACT_SCOPE=generated_task_plan`, focus on `technical_plan`
  and `worktree_plan`, and cross-check stored `epic_tasks` against the written
  plan.
- Any status with substantive `shepherd_caveats`: refine `shepherd_caveats` so open questions and deferrals are crisp and actionable.
- If no structured field exists yet, refine the authoritative fallback (`body`) but keep the resulting content ready to migrate into structured fields later.

### 4b. Effective File Budget And Path-Claim Re-Check

Use `ITEM_FILE_BUDGET_POLICY`, `ITEM_PATH_CLAIMS_POLICY`, and their scoped
policies resolved from the immutable pin in step 1:

- Both enabled: confirm path-claim coverage matches the refined File Budget.
- Budget off / claims on: derive claim paths from the item spec or linked
  execution document; do not create a File Budget as a proxy.
- Budget on / claims off: refine the budget for sizing and conflict evidence;
  do not register a claim.
- Both off: skip artifact/gate requirements for both axes.

The universal 350-line authored-file limit remains enforced in every posture.
Run the path-claim gate only when effective path claims are enabled:

```bash
yoke claims path required-gate PREFIX-{N}
```

Branch on the result:

- **verdict=pass** — no action required; continue to step 5. When both axes
  are enabled and refine narrows the File Budget, record the planned claim
  narrow-down as a critique item; the actual `path-claims narrow` runs in
  step 6.
- **verdict=pass with pre-task deferral** — for a
  `required_per_task` Epic with no generated tasks, do not register or widen an
  item-level claim. Shepherd owns materialization from persisted task budgets.
- **verdict=block** — STOP. Author or amend the claim before proceeding. Three options, picked from the same decision matrix as idea. The canonical product CLI is `yoke claims path register …`; checkout-local db-router registration is operator-debug fallback only.
  1. Register a new exclusive claim (`yoke claims path register --paths …`)
     from the enabled File Budget or, when budget is off, the derived
     execution touch set.
  2. Register with `--allow-planned` when that source names future files.
  3. Register a no-claim exception (`--mode exception --reason "..."`) when refine determines the item legitimately touches no repo surface.

  For `required_per_task` with generated tasks, repair each failing task with
  `yoke claims path register --item PREFIX-N --task-num <N> ...`; an unbound
  parent claim never satisfies this verdict.

  When registration fails due to overlap with a non-terminal claim owned by another item, classify the overlap via `yoke claims path coordination-decision-build` and author either `--gate-point coordination_only` (compatible overlap with no lifecycle gate, default for independent same-file edits) or explicit `--gate-point activation` with directional rationale (order-dependent edits). See [`readiness-repair.md`](readiness-repair.md) `## Cross-item overlap repair`.

When both axes are enabled and refine widens the File Budget mid-pass
(discovers additional files), use `yoke claims path widen --claim-id <id>
--add-paths <added> --reason "<why widening>" --item PREFIX-N` rather than
registering a fresh claim — widen preserves the audit trail in
`path_claim_amendments`. If refine narrows, use the checkout-local
`path-claims narrow` operator-debug/refine disposition; no public narrow
wrapper is registered yet. Prefer the `--keep-paths` form because it names
the paths that stay (`--reason` is required); use `--drop-paths` when the goal
is to remove specific files from a wider claim instead.

The claim re-check is **blocking**: refine MUST NOT advance the item past
`REFINE_ACTIVE_STATUS` while the gate returns `block`. The lifecycle event
gate `GATE_DB_CLAIM_PROSE_MISMATCH` only covers DB-mutation claims; this gate
is the path-claim equivalent and runs alongside it.

### 5. Critique

Read [`review-rubric.md`](review-rubric.md) for the full critique dimensions,
mandatory checks, and artifact-specific rubrics. Emit its structured critique.
When effective File Budget is enabled, its rubric is first-class: an
implementation-bearing item must not advance to `REFINE_TARGET_STATUS` with a
missing, vague, or unresolved File Budget; see `update-protocol.md`'s
**File Budget escalation**. When disabled, skip section authoring while still
critiquing the plan against the universal 350-line cap.

### 6-12. Apply Improvements, Verify, Link Blitz Plan, Advance, Release, Final Output

Read [`update-protocol.md`](update-protocol.md) for the full update protocol: applying additive improvements (step 6), verifying writes (step 7), capturing the final summary (step 8), advancing status on success (step 9), releasing the item claim (step 10), final output (step 11), and completion criteria (step 12).

When `ITEM_NEXT_EXECUTOR=blitz`, read and follow
[`blitz-execution-document.md`](blitz-execution-document.md) after step 7 and
before step 9. Refine is not complete until the registered link write has
been verified through `strategy.execution.get`.

### Final phase — Policy-Aware Path Closure (before status advance)

Refine MUST NOT advance from `REFINE_ACTIVE_STATUS` to
`REFINE_TARGET_STATUS` until every enabled axis is complete. Run the readiness
check once more after critique-driven updates and before the status mutation
in step 9:

```bash
yoke readiness check {N}
```

The exit condition is the same as idea's policy-aware path closure:

- When File Budget is enabled, every file the implementer will edit is
  enumerated in `## File Budget`, one path per line. **Counts and
  approximations ("roughly 30 files", "every caller", "all importers") are
  not acceptable** in place of enumerated paths.
- When path claims are enabled, coverage is complete from the enabled File
  Budget or, when budget is off, from the execution artifact/investigation.
- Only when both axes are enabled does this phase require parity between them.
- The readiness check returns exit 0.

If the check fails or the spec still contains unexpanded prose substitutes for enumeration, do NOT advance. Either complete the enumeration in this pass or stop and surface the gap to the operator. The boundary gate at advance time exists as a tripwire, not as a fallback for refine skipping closure.

When File Budget is enabled, **only physical files belong in `## File
Budget` list-item backticks.** Function ids (`items.section.upsert`), event
names, command surfaces, and other operational references go in the
surrounding spec prose.

### Multi-turn refine session continuity

Refine writes go to the structured fields the protocol names (`spec`,
`design_spec`, `technical_plan`, `worktree_plan`, `shepherd_caveats`). Those
are intent/design surfaces, not scratchpads for in-flight state. If a pass
spans multiple turns, write checkpoint notes to the item's **Progress Log**;
successor agents use it to learn what is complete, pending, and settled.
