---
name: refine
description: "Read item artifacts, critique them, and write improved ticket artifacts back through sanctioned Yoke update surfaces."
argument-hint: "{YOK-N}"
---

# /yoke refine {YOK-N}

Standalone capability for refining backlog item artifacts. Reads the item's structured fields, critiques them for completeness, clarity, and testability, and writes improved content back through sanctioned Yoke update surfaces.

This is an explicit, operator-invoked capability that Codex can execute directly. It does not require `/yoke do`, lane-aware routing, or lifecycle-family ownership wiring.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug not worth a ticket, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Arguments

- `{YOK-N}` — Backlog item ID. Accepts prefixed IDs, zero-padded prefixed IDs, or bare numeric IDs.

## Modes

Refine always advances status on successful completion, whether invoked directly (e.g., `/yoke refine YOK-N`) or via scheduler routing.

### Lifecycle transitions

**Idea refinement (issue and epic):**
- `idea` -> `refining-idea` (set at start of work)
- `refining-idea` -> `refined-idea` (set on successful completion)

**Plan refinement (epic only):**
- `plan-drafted` -> `refining-plan` (set at start of work)
- `refining-plan` -> `planned` (set on successful completion)

If refine fails or is interrupted, the item must NOT auto-advance past its current status. The item stays at its current status (`idea`, `refining-idea`, `plan-drafted`, or `refining-plan`).

## Constraints

- No worktree required.
- No code edits or commits.
- Artifact writes are work writes: ticket/spec/body sections, File Budget, path-claim register/widen/narrow/release, and GitHub issue-body edits are shared coordination state; hold the item claim before mutating them, and treat `who-claims` session ids as identifiers, not authority.
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

## Entry Backstop

The idempotent non-browser QA requirement backstop is a **claim-requiring** op, so it runs inside step 1b immediately after the work claim is acquired — never before the claim. Running it before the claim fails with `claim_required` (it self-corrects via the recovery hint, but the ordering should not produce the avoidable failure). The recipe lives in step 1b below. `yoke qa requirement auto-create-for-item --help` documents the worked example, outcome vocabulary, and flag matrix.

## Philosophy

### Cardinal Rule: Never subtract, only add

Refine enhances artifacts by adding what's missing — it never removes, replaces, or paraphrases existing content. The operator's words, questions, evidence, decisions, and ACs are input constraints, not rough drafts to be polished. You may add sections, add ACs, add verification commands, add blast-radius analysis, add scope boundaries, and add cross-references. You may improve wording **in place** (grammar, clarity) without changing meaning. You may NOT delete content, abstract specifics into generalities, paraphrase user questions into scope language, or replace concrete statements with vague ones.

Every rewrite is a lossy transformation. Refine does not rewrite — it enhances in place and appends.

### Escalate, don't correct

If the spec contains a major error — wrong file references, contradictory requirements, a fundamentally flawed approach, scope that conflicts with existing work — do NOT silently fix it. **Stop and surface the issue to the operator.** The operator may have context you don't. Refine is not authorized to make judgment calls about what the operator "really meant" when the spec contradicts reality. Do NOT advance status. Leave the item at `refining-idea` or `refining-plan` and report what you found.

### Corollaries (reinforcing the cardinal rule)

**Concrete decisions are sacred.** If the spec already contains concrete structural decisions — directory trees, file layouts, explicit "X stays at Y" / "X moves to Y" statements, specific naming choices, architectural diagrams, or interface shapes — those represent decisions the operator already approved. You may add discovery commands around them, add blast-radius analysis, or add supporting ACs — but you may NEVER abstract a concrete decision into vague prose. "`runtime/harness/` subpackage unifies all harness code with claude/ and codex/ subdirs" is a concrete decision. "A single truthful ownership model for harness code" is an abstraction that loses the decision.

**ACs are additive, not replacive.** You may add new ACs, renumber, improve wording, and add verification commands. You may NOT delete or replace the substance of an existing AC. Every concrete AC in the original must have a corresponding concrete AC in the enhanced version.

**User voice is verbatim.** When the spec contains content that is clearly the user's own words — numbered questions, direct observations, screenshots, "I saw X", "why does X", evidence references — that content must be preserved word-for-word. User questions define what the ticket must answer; user evidence defines the ground truth the ticket must address. Abstracting "what's the point of running CI in parallel with deployments?" into "document the tradeoff" loses the question the ticket exists to answer.

### Operating principles

**Maximalist interpretation.** Read every ticket as "make this fully work end-to-end so the operator can use and experience the result." A minimal interpretation that leaves obvious end-to-end requirements for a hypothetical future ticket is a refinement failure. If a reasonable person would expect it to work, the ticket should say so.

**Surface what's missing, not just what's unclear.** Refinement fills in what the operator obviously meant but didn't write. Missing error handling, missing cleanup of replaced state, missing documentation updates, missing blast-radius items. Do not fabricate unrelated scope or redesign the ticket's purpose, but do complete the picture of what "done" actually looks like.

**Clean-slate mindset.** If the ticket replaces, removes, or supersedes something, the spec must explicitly call out what gets deleted. The codebase after this ticket should read as if the old way never existed.

**Simplest migration wins.** Default to hard cutover unless there is provably live data, live users, or live integrations that need graceful migration.

**Future-concept lens.** Generation labels are sequencing hints, not architecture walls. If a ticket adds or changes `actor_id`, `session_id`, `heartbeat_at`, ownership, leases, claims, approvals, overrides, evidence, run records, execution journals, compiled packets, route-around facts, resource locks, or shared-state coordination, refine must decide whether this is the smallest honest v0 of a later end-state primitive. If yes, shape the spec around that primitive and the concrete current consumers. If no, require an explicit deletion or absorption target so a local workaround does not become accidental architecture.

**Dead weight has zero tolerance.** If the ticket obsoletes code, tests, config keys, feature flags, utility functions, documentation sections, migration scripts, or re-exports, the spec must include their removal.

**Be the giant.** Your refined artifacts are the cold-start context for every downstream agent. Every gap you leave is a gap they'll hit. Do the investigative legwork: verify code references against the live codebase, include grep commands for blast-radius discovery, provide concrete examples.

**No such thing as "agent error."** When the critique reveals a bad artifact, the cause is systemic: insufficient dispatch context, ambiguous instructions, or upstream gaps. Frame every issue as what the SYSTEM should change to prevent it.

**Events table for investigation.** When critiquing artifacts, query the events table for diagnostic context: `yoke events query --item {N}`. Anomaly flags and envelope data reveal whether the artifact was produced under context pressure.

**File tickets for root causes.** When refinement surfaces a systemic issue, note the root cause for ticket filing.

**Think, don't just check.** The dimensions and rules in this skill are a starting point, not a ceiling. Step back and think about the ticket as a whole: What is this ticket actually trying to achieve? What would a thoughtful senior engineer expect "done" to look like? The checklist catches known failure modes; your judgment catches everything else.

## Steps

### 1. Parse And Lookup

Resolve the repo root and look up the item through the unified DB router.

```bash
MAIN_ROOT=$(git rev-parse --show-toplevel)
ITEM_NUM=$(printf '%s' "{arg}" | sed 's/^[Ss][Uu][Nn]-//; s/^0*//')
ITEM_TYPE=$(yoke items get "$ITEM_NUM" type 2>/dev/null) || ITEM_TYPE=""
ITEM_STATUS=$(yoke items get "$ITEM_NUM" status 2>/dev/null) || ITEM_STATUS=""
ITEM_TITLE=$(yoke items get "$ITEM_NUM" title 2>/dev/null) || ITEM_TITLE=""
```

If any of those reads come back empty, stop with:
> Item YOK-{N} not found.

### 1b. Claim and Set Entry Status

Determine the refinement phase based on item type and current status:

**Idea refinement (issue and epic):**
- If status is `idea`: advance to `refining-idea` before starting work.
- If status is `refining-idea`: proceed without changing status (re-entry support).

**Plan refinement (epic only):**
- If `ITEM_TYPE` is `epic` and status is `plan-drafted`: advance to `refining-plan` before starting work. Record that the entry phase is plan refinement so step 9 advances to `planned` instead of `refined-idea`.
- If `ITEM_TYPE` is `epic` and status is `refining-plan`: proceed without changing status (re-entry support). Record that the entry phase is plan refinement so step 9 advances to `planned` instead of `refined-idea`.

If the item is at any other status, stop with:
> **Cannot refine YOK-{N}:** Item is at `{status}`, expected `idea` or `refining-idea` for idea refinement, or `plan-drafted` or `refining-plan` for epic plan refinement.

Register the work claim BEFORE the status transition (claim-before-status ordering). The session stamp uses the registered session wrapper. This prevents the scheduler from offering the same item while refine is actively working on it, and ensures the subsequent status mutation passes claim verification:

```bash
ITEM_NUM=$(printf '%s' "{arg}" | sed 's/^[Ss][Uu][Nn]-//; s/^0*//')
# Session touch + claim (AC-4)
yoke sessions touch --mode refine
yoke claims work acquire \
 --item "YOK-$ITEM_NUM"
# Entry QA backstop — claim-requiring, so it runs AFTER the work claim above (never before).
yoke qa requirement auto-create-for-item --item "YOK-$ITEM_NUM"
```

For idea refinement, run the internal pre-handoff readiness gate before the
entry status mutation. Read and follow
[`readiness-repair.md`](readiness-repair.md) for the full classifier
table (`pass` / `pure_stale_count` auto-fix / `FILE_BUDGET_NOT_IN_CLAIM`
auto-widen / `mixed_stale_count` continuation / `unrecoverable`
terminal block), the routing rationale, and the `/yoke do`
chain-step contract. The recipe inlined below mirrors the phase doc:

```bash
if [ "$ITEM_STATUS" = "idea" ]; then
 _readiness_json=$(yoke readiness check "$ITEM_NUM" 2>/dev/null) || true
 _advisories=$(printf '%s' "$_readiness_json" | python3 -c "
import json, sys
data = json.loads(sys.stdin.read() or '{}')
print('\\n'.join(a.get('message','') for a in data.get('advisories', []) if a.get('message')))
")
 if [ -n "$_advisories" ]; then
  printf 'Readiness advisories:\\n%s\\n' "$_advisories"
 fi
 _class=$(printf '%s' "$_readiness_json" | python3 -c "
import json, sys
data = json.loads(sys.stdin.read() or '{}')
print(data.get('classification', 'unrecoverable'))
")
 case "$_class" in
  pass) ;;
  pure_stale_count)
   yoke readiness repair-stale-count --item "$ITEM_NUM" || {
    yoke sessions checkpoint --step 1 --action refine --chainable false --outcome blocked --item-id "YOK-$ITEM_NUM"
    yoke claims work release \
     --item "YOK-$ITEM_NUM" --reason "readiness-check-blocked" >/dev/null 2>&1 || true
    exit 1
   }
   ;;
  mixed_stale_count)
   yoke readiness repair-claim-coverage --item "$ITEM_NUM" || {
    printf 'Recoverable readiness gaps not auto-repaired; continuing into refine for repair:\n%s\n' "$_readiness_json"
   }
   ;;
  unrecoverable)
   printf '%s\n' "$_readiness_json"
   yoke sessions checkpoint --step 1 --action refine --chainable false --outcome blocked --item-id "YOK-$ITEM_NUM"
   yoke claims work release \
    --item "YOK-$ITEM_NUM" --reason "readiness-check-blocked" >/dev/null 2>&1 || true
   exit 1
   ;;
 esac
fi
```

Then set the entry status via the `lifecycle.transition.execute`
function call (envelope in
[`../idea/body-and-sync-functions.md`](../idea/body-and-sync-functions.md)):

- For `idea -> refining-idea`: `payload = {target_status:
  "refining-idea", source_status: "idea"}`.
- For `plan-drafted -> refining-plan` (epic only): `payload =
  {target_status: "refining-plan", source_status: "plan-drafted"}`.

### 2. Gather Artifacts

Read all available structured fields. Empty fields are normal; refinement should still inspect them and decide whether a light structural improvement is warranted.

```bash
MAIN_ROOT=$(git rev-parse --show-toplevel)
ITEM_NUM=$(printf '%s' "{arg}" | sed 's/^[Ss][Uu][Nn]-//; s/^0*//')
BODY=$(yoke items get "$ITEM_NUM" body 2>/dev/null) || true
SPEC=$(yoke items get "$ITEM_NUM" spec 2>/dev/null) || true
DESIGN_SPEC=$(yoke items get "$ITEM_NUM" design_spec 2>/dev/null) || true
TECHNICAL_PLAN=$(yoke items get "$ITEM_NUM" technical_plan 2>/dev/null) || true
WORKTREE_PLAN=$(yoke items get "$ITEM_NUM" worktree_plan 2>/dev/null) || true
SHEPHERD_CAVEATS=$(yoke items get "$ITEM_NUM" shepherd_caveats 2>/dev/null) || true
```

For planned epics, also inspect the current task decomposition:

```bash
MAIN_ROOT=$(git rev-parse --show-toplevel)
ITEM_NUM=$(printf '%s' "{arg}" | sed 's/^[Ss][Uu][Nn]-//; s/^0*//')
EPIC_TASKS=$(yoke epic-tasks list --epic "$ITEM_NUM" 2>/dev/null) || true
```

If all fields are empty or trivial, emit:
> **Advisory:** YOK-{N} has minimal content. Consider populating the body first or running `/yoke shepherd YOK-{N}` before refining.

Proceed anyway — refinement can still add structure to sparse items.

### 3. Contextual Survey

**This step is critical.** Refinement in isolation produces stale, duplicated, or conflicting artifacts. Before critiquing the item, survey the surrounding landscape to ground the critique in reality.

**Recent commits** — What has actually landed recently? The item's assumptions about current codebase state may be outdated.

```bash
MAIN_ROOT=$(git rev-parse --show-toplevel)
git -C "$MAIN_ROOT" log --oneline -20
```

Scan for commits that touch the same files, functions, or subsystems as this item. If recent work has already addressed part of this item's scope, note it — the spec may need descoping or the item may be partially done.

**Active and pipeline tickets** — What else is in flight or queued that overlaps?

```bash
MAIN_ROOT=$(git rev-parse --show-toplevel)
python3 -m yoke_core.cli.db_router query "SELECT id, status, title FROM items WHERE status IN ('implementing','reviewing-implementation','reviewed-implementation','polishing-implementation','refining-idea','refined-idea','planning','refining-plan','planned') ORDER BY id DESC"
```

Look for:
- **Overlap** — another ticket targeting the same files, functions, or behavior. Flag it in the critique and ensure the spec acknowledges the overlap or deconflicts.
- **Supersession** — a broader ticket that subsumes this one. If so, recommend absorbing or cancelling.
- **Dependencies** — a ticket that must land first for this item's assumptions to hold, or vice versa.

**Recently done tickets** — What just shipped that might affect this item's assumptions?

```bash
MAIN_ROOT=$(git rev-parse --show-toplevel)
python3 -m yoke_core.cli.db_router query "SELECT id, title FROM items WHERE status='done' ORDER BY id DESC LIMIT 15"
```

Check whether recently completed work has:
- Already solved part of this item's problem (descope needed).
- Changed the codebase in ways that invalidate the item's spec, file references, or approach.
- Created new capabilities that this item should leverage instead of building from scratch.

**Staleness check** — Synthesize findings from the three queries above. An item is stale when:
- Its spec references files, functions, or behaviors that have been renamed, removed, or significantly refactored since the spec was written.
- Its problem statement describes a symptom that has already been fixed.
- Its approach assumes codebase state that no longer exists.
- Its scope overlaps with another active or recently-done ticket in any way — same files, same behavior, same problem from a different angle. Any overlap must be resolved: descope, absorb, dependency-link, or cancel.

Carry ALL survey findings into the critique in step 5. Staleness and overlap are first-class refinement issues, not optional observations.

### 4. Choose The Refinement Focus

Pick the field(s) to refine based on the current status and whatever structured content actually exists:

- `idea` / `refining-idea` / `refined-idea` / `defined` / `designed`: focus on `spec` first, then `design_spec` if the item already has UX or flow detail.
- `planned` / `refining-plan`: focus on `technical_plan`, `worktree_plan`, and for epics also cross-check the stored epic tasks against the written plan.
- Any status with substantive `shepherd_caveats`: refine `shepherd_caveats` so open questions and deferrals are crisp and actionable.
- If no structured field exists yet, refine the authoritative fallback (`body`) but keep the resulting content ready to migrate into structured fields later.

### 4b. Path-Claim Re-Check

Refine is the second of two structural opportunities (idea is the first) to confirm that the item's path-claim coverage matches the refined File Budget. Run the internal gate before critique so the critique has the latest claim state to reason against:

```bash
yoke claims path required-gate YOK-{N}
```

Branch on the result:

- **verdict=pass** — no action required; continue to step 5. If refine narrows the File Budget (drops files, identifies a no-claim posture), record the planned narrow-down as a critique item; the actual `path-claims narrow` runs in step 6.
- **verdict=block** — STOP. Author or amend the claim before proceeding. Three options, picked from the same decision matrix as idea. The canonical product CLI is `yoke claims path register …`; checkout-local db-router registration is operator-debug fallback only.
  1. Register a new exclusive claim (`yoke claims path register --paths …`) when the File Budget names existing files.
  2. Register with `--allow-planned` when the File Budget names future files.
  3. Register a no-claim exception (`--mode exception --reason "..."`) when refine determines the item legitimately touches no repo surface.

  When registration fails due to overlap with a non-terminal claim owned by another item, classify the overlap via `yoke claims path coordination-decision-build` and author either `--gate-point coordination_only` (compatible overlap with no lifecycle gate, default for independent same-file edits) or explicit `--gate-point activation` with directional rationale (order-dependent edits). See [`readiness-repair.md`](readiness-repair.md) `## Cross-item overlap repair`.

If refine widens the File Budget mid-pass (discovers additional files), use `yoke claims path widen --claim-id <id> --add-paths <added> --reason "<why widening>" --item YOK-N` rather than registering a fresh claim — widen preserves the audit trail in `path_claim_amendments`. If refine narrows, use the checkout-local `path-claims narrow` operator-debug/refine disposition; no public narrow wrapper is registered yet. Prefer the `--keep-paths` form because it names the paths that stay (`--reason` is required); use `--drop-paths` when the goal is to remove specific files from a wider claim instead.

The claim re-check is **blocking**: refine MUST NOT advance the item past `refining-idea` (or `refining-plan` for epics) while the gate returns `block`. The lifecycle event gate `GATE_DB_CLAIM_PROSE_MISMATCH` only covers DB-mutation claims; this gate is the path-claim equivalent and runs alongside it.

### 5. Critique

Read [`review-rubric.md`](review-rubric.md) for the full critique dimensions, mandatory checks (approved decisions inventory, user-provided input inventory, staleness/overlap, events forensics, reference verification, blast radius discovery, cleanup coverage, failure/recovery coverage, open-question closure, prompt/file-size awareness, **File Budget readiness**), and artifact-specific evaluation rubrics for body/spec, design spec, technical plan/worktree plan, and shepherd caveats. Emit the structured critique as described there. The File Budget rubric is first-class — implementation-bearing items must not advance to `refined-idea` (issue) or `planned` (epic) with a missing, vague, or unresolved File Budget; see `update-protocol.md`'s **File Budget escalation** for the operator handoff path when refine cannot resolve it.

### 6-12. Apply Improvements, Verify, Advance, Release, Final Output

Read [`update-protocol.md`](update-protocol.md) for the full update protocol: applying additive improvements (step 6), verifying writes (step 7), capturing the final summary (step 8), advancing status on success (step 9), releasing the item claim (step 10), final output (step 11), and completion criteria (step 12).

### Final phase — Path Closure (before status advance)

Refine MUST NOT advance status (`refining-idea -> refined-idea` or `refining-plan -> planned`) until the File Budget and the path-claim are complete and consistent. Run the readiness check once more after critique-driven updates have landed and before the status mutation in step 9:

```bash
yoke readiness check {N}
```

The exit condition is the same as idea's path closure:

- Every file the implementer will edit is enumerated in `## File Budget`, one path per line. **Counts and approximations ("roughly 30 files", "every caller", "all importers") are not acceptable** in place of enumerated paths. If the spec contains such prose, the refine pass must expand it — investigate (grep / sub-agents / codebase reading) and write the enumeration into the spec body.
- The path-claim's declared paths cover everything in the File Budget. Step 4b already gated entry; this final pass catches drift introduced by critique edits in step 6.
- The readiness check returns exit 0.

If the check fails or the spec still contains unexpanded prose substitutes for enumeration, do NOT advance. Either complete the enumeration in this pass or stop and surface the gap to the operator. The boundary gate at advance time exists as a tripwire, not as a fallback for refine skipping closure.

**Only physical files belong in `## File Budget` list-item backticks.** Function ids (`items.section.upsert`), event names, command surfaces, and other operational references go in the surrounding spec prose — not in the `- ` list-item backticks the readiness parser inspects. The dotted-identifier carve-out in `yoke_core.domain.file_budget_paths` silently drops them, but refine should strip them out of the budget entirely so the next reader sees only enumerated paths.

### Multi-turn refine session continuity

Refine writes go to the structured fields the protocol names (`spec`, `design_spec`, `technical_plan`, `worktree_plan`, `shepherd_caveats` for epics). Those are intent/design surfaces — NOT scratchpads for in-flight refinement state. If your refine pass spans multiple turns (large epic plan revision, multi-section critique cycle), write checkpoint notes to the **Progress Log** section on the item — see `AGENTS.md > Progress Log — long-running execution context on items`. Successor agents read it on cold start to learn what's already been critiqued, what's pending, and which decisions are settled.
