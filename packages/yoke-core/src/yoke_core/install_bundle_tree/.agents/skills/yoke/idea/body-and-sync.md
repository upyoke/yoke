# Idea Phase: Persist Body And Sync

This phase owns the mandatory body write, additive-only handling, AC normalization, verification, and GitHub body sync for `/yoke idea`.

## 8. Persist The Body

This step is mandatory, not optional.

### Body detection

Scan the user's message for body content. Any text beyond the title counts as a description. This includes inline descriptions, multi-line specs, references to plans, implementation details, acceptance criteria, or any other context the user provided. Do not silently discard it.

### Additive-only rule

You may add structure, headings, cross-references, or clarifying notes. You must not summarize, condense, paraphrase, or omit any of the user's original content. Every line, code block, mockup, table, and ASCII artifact the user wrote must appear verbatim in the body.

### Simplify pre-check (advisory)

Every new body carries a `## Simplify Pre-Check` block applying the simplify three-axis vocabulary at the idea stage. The vocabulary lives in `AGENTS.md`'s `## Simplify — three-axis doctrine` section: **reuse**, **quality**, **efficiency**. The pre-check is **advisory, not a blocker** — its structural presence at intake matters more than its depth. A one-line "no concerns" entry under each axis is a valid first pass.

- **Reuse** — does an existing ticket, completed feature, Pack, helper, skill, or command surface already cover this outcome? If unsure, name what was searched.
- **Quality** — is this one concrete outcome, or a bundle that should split or become an epic? Are there explicit non-goals that prevent scope creep?
- **Efficiency** — is this speculative transitional work ("do X so maybe later we can do Y") when Y is not committed? Or the cheapest valuable path?
- **Future-concept lens** — if the idea mentions actors, sessions, heartbeats, ownership, leases, claims, approvals, overrides, evidence, runs, journals, packets, locks, or shared-state coordination, should it consume/pull forward an end-state primitive instead of creating a temporary local surface?
- **Codebase-reader naming** — assume future readers will not have the ticket, strategy doc, plan, phase, task, or AC that produced this work. Any proposed file, module, helper, test, doc, command, event, config key, or symbol must be named for current function/purpose/mechanics, not for planning-artifact provenance.

Compose the block as part of the body content the user provided. Example:

```markdown
## Simplify Pre-Check

- Reuse: no relevant existing surface (searched `rg ...`).
- Quality: one concrete outcome (no scope creep).
- Efficiency: no concerns.
- Future-concept lens: no later-generation primitive implicated.
- Codebase-reader naming: proposed names describe current functionality, not planning artifacts.
```

### File Budget (upstream of the 350-line cap)

The full File Budget contract — required structure, current line counts, sibling-module plan when any file is at-cap, File Budget vs path-claim consistency — lives in [`file-budget.md`](file-budget.md). Read it once and keep applying its rules to every implementation-bearing intake.

File Budget paths and responsibility notes must pass the codebase-reader naming rule from `AGENTS.md`: do not name expected files after the ticket, strategy doc, plan, phase, task, AC, branch, or worktree that produced the work. Name the file by the current responsibility a future repository reader will see.

**Single-pass File Budget + path-claim authoring.** The File Budget
section (here) and the path claim registered in section 9b are **two
faces of the same enumeration** — the same list of files appears in
both. Author them together in one pass: when you write a path into the
File Budget, add it to the path-claim `--paths` set in the same pass.
When the path-claim attempt blocks on an overlap, keep the path in both
surfaces and route to `path-claim-blocking.md` rather than narrowing
either. The release-after-pass gate at section 10b runs
`idea_readiness_check` to verify the two surfaces agree; a
mismatch leaves the draft claim held and blocks creation from
finishing.

Every new body for an **implementation-bearing** ticket carries a `## File Budget` section. The hard limit is 350 lines per authored file (owned by `yoke_core.domain.file_line_check`); the design target is `<=300` lines so implementors have editing headroom without crossing the cap mid-iteration. Idea-time the budget can be rough — the goal is to force the sizing question into the artifact before refinement, planning, and implementation, so an Engineer is never asked to invent a large module from scratch.

Three valid shapes — pick the one that matches what the operator described:

1. **Implementation-bearing, known shape** — name the likely files/modules and a one-line single responsibility for each.
2. **Implementation-bearing, unknown shape** — record the work as creating/growing authored code AND mark the budget unresolved so `/yoke refine` is forced to resolve it before `refined-idea`.
3. **Non-code (docs-only / config-only / no authored-code growth)** — record `N/A` plus a one-line reason. If implementation later discovers authored-code work, refine/advance must add a real File Budget before coding begins.

Compose the block immediately after `## Simplify Pre-Check` so it is
visible before acceptance criteria. Three valid examples:

```markdown
## File Budget

- Hard limit: 350 lines per authored file.
- Design target: <=300 lines per authored file.
- Expected implementation shape:
  - `path/to/file_a.py` — single responsibility A
  - `path/to/file_b.py` — single responsibility B
```

```markdown
## File Budget

UNRESOLVED — this ticket creates/grows authored code but the file shape is not yet known. `/yoke refine` MUST resolve the expected implementation shape before this item advances past `refining-idea`.
```

```markdown
## File Budget

N/A — docs-only updates to README. If implementation discovers authored-code changes, refine/advance must add a real File Budget before coding.
```

The File Budget is upstream guidance, not a write-time denial —
late-stage enforcement (`yoke_core.domain.file_line_check`) is the
canonical backstop. The contract here shapes the work earlier so
implementors are not asked to invent oversized modules in the first
place.

### AC format rule

**Always use checkbox format for acceptance criteria.** Write `- [ ] AC-N: {description}` — never bare `- AC-N:` or `- ACN:`. The advance AC-presence gate requires checkboxes; writing them correctly here avoids a round-trip rewrite later.

### If the user provided body content

1. Compose the full body content and dispatch it through the
   `items.structured_field.replace` function call (see
   [`body-and-sync-functions.md`](body-and-sync-functions.md) for the
   envelope shape and payload contract):

   - `function = "items.structured_field.replace"`
   - `target = {kind: "item", item_id: <id>}`
   - `payload = {field: "spec", content: "<full body>", source: "idea", force: false}`

   The body content is the same per-section composition the prior
   choreography emitted (title + verbatim user content + the
   `## Pack Reuse` block when `_pack_stance` is non-empty).
   The handler enforces the empty-payload / shrinkage / freeze guards
   and emits `YokeFunctionCalled` plus the field-specific update event.
   Operator/debug adapter: Write the body to a local artifact via the harness Write tool, then `yoke items structured-field replace YOK-{id-number} --field spec --source idea --stdin < <artifact-path>` (inline shell payloads are denied by `lint_shell_quoted_function_payload`).

2. Normalize non-canonical ACs when needed: the live `python3 -m yoke_core.domain.normalize_ac_labels` reads stdin or `--file FILE` (no `--item`); normalization of DB-resident specs runs inside `/yoke shepherd YOK-{id-number}`.

3. Verify the body was written via `items.get.run`
   (`fields: ["spec", "body"]`). If the returned `spec` contains only
   `# {title}` or is empty, retry the `items.structured_field.replace`
   call once.

### If the user provided no body content

Ask the user explicitly:
> Do you want to add a description? (Yes / No)

If yes, collect the description and run the same body-write flow. If no, still write a minimal spec containing `# {title}` plus `## Simplify Pre-Check` with one-line entries for reuse, quality, efficiency, the future-concept lens, and codebase-reader naming (for example, `no concerns from title-only intake`) AND a `## File Budget` section using the appropriate shape from the section above. The pre-check is advisory; the File Budget is mandatory for any implementation-bearing intake. A title-only ticket whose nature is genuinely unknown should record the File Budget as `UNRESOLVED` so refine resolves it before implementation, or `N/A` with a reason if the operator confirmed no authored code will change.

Important: do not edit a rendered body directly. Always update via the
structured-field function calls — `items.structured_field.replace` for
full rewrites, `items.structured_field.append_addendum` /
`section_upsert` / `section_append` for additive transforms. See
[`body-and-sync-functions.md`](body-and-sync-functions.md).

## 8b. Late DB-Claim Classification

After the body has been written and verified (step 8 complete), classify and persist the DB claim against the **finished spec**, not against the title-only draft. This is the same amendment workflow `/yoke refine`, `/yoke advance`, and `/yoke polish` use later — there is no separate "first classification" path.

**Why bucket discipline matters:** The prose-vs-claim gate honors any `DbClaimAmended` event with `state="none"` and `validation_result="pass"` as cleared evidence regardless of the reason text. The three-bucket discipline below is therefore the only signal that distinguishes reviewed-none meta-tickets from silent deferral bypasses; getting the bucket right at idea time is load-bearing.

1. Run the prose-vs-claim detector against the freshly written spec/body:

   ```bash
   _prose_check=$(python3 -m yoke_core.domain.db_claim_prose_check check-item "YOK-{N}")
   _prose_blocks=$(printf '%s' "$_prose_check" | python3 -c "import json,sys; print('1' if json.load(sys.stdin).get('blocks') else '0')")
   ```

2. **No triggers detected (`_prose_blocks=0`):** explicitly stamp the
   negative-default claim through the canonical workflow so the item
   carries an event-attested `state="none"` rather than the implicit
   creation default. Dispatch the `db_claim.amend` function call
   (envelope in
   [`body-and-sync-functions.md`](body-and-sync-functions.md)) with
   `target = {kind: "item", item_id: <id>}` and
   `payload = {reason: "idea: spec/body declares no governed DB mutation", claim: {state: "none"}}`.

   The reason text is canonical — do not paraphrase. It is the only
   `state="none"` reason emitted on the no-DB-work path.

3. **Triggers detected (`_prose_blocks=1`):** the agent presents the
   matched triggers, then asks one ternary question. The buckets are
   mutually exclusive, and `state="none"` is **not** a valid deferral
   path for real governed mutation — pick the bucket that actually
   describes this ticket's deliverables. Canonical prompt:

   > Spec declares governed DB vocabulary (`{triggers}`). Pick one:
   >
   > 1. **Real governed mutation, declare now** (Bucket 1) — gather model, mutation intent, migration module slug, compatibility class, and (for `pre_merge_safe`) the four authored attestation fields. Dispatch `db_claim.amend` with the unified declared `claim` payload (see [.yoke/docs/db-reference.md](../../../../.yoke/docs/db-reference.md)).
   > 2. **Real governed mutation, blocker for refine** (Bucket 2) — append a `DB Claim Blocker (idea-time)` section via `items.structured_field.section_upsert` listing known + missing facts. Do NOT call `db-claim-amend`; do NOT dispatch `db_claim.amend` — the implicit `{"state":"none"}` default plus the missing event signals `/yoke refine` to block at `GATE_DB_CLAIM_PROSE_MISMATCH` until a declared payload lands.
   > 3. **Meta-ticket about DB governance** (Bucket 3) — the ticket cites DB vocabulary but its own deliverables do not mutate any governed authoritative DB (skill prose, gate composition, prose-classifier patterns, audit-trail vocabulary). Dispatch `db_claim.amend` with `payload.claim = {state: "none"}` and `payload.reason = "idea: ticket discusses DB governance vocabulary but performs no governed DB mutation; reviewed-none"`. The literal `; reviewed-none` suffix is the canonical signal — do not paraphrase.

   Bucket 2 blocker section template:

   ```
   ## DB Claim Blocker (idea-time)

   This ticket performs governed DB mutation but the declared claim could not be authored at idea time. `/yoke refine` MUST dispatch `db_claim.amend` with a declared `claim` payload before this item can advance past `refining-idea`.

   Known facts:
   - Authoritative DB / model: {known-or-unknown}
   - Mutation intent (apply / retire): {known-or-unknown}
   - Migration module slug (planned): {known-or-unknown}
   - Compatibility class (pre_merge_safe / pre_merge_breaking): {known-or-unknown}
   - Affected surfaces: {free-form list}

   Missing facts that block declared payload:
   - {item}
   ```

4. Verify the claim landed (buckets 1 and 3 only — bucket 2 leaves the
   schema default in place by design) via the `items.get.run` function
   call with `fields: ["db_mutation_profile"]`.

This step is mandatory. The amendment workflow is upsert-safe
(idempotent against missing prior state) and emits a `DbClaimAmended`
event, so the audit trail shows the claim was deliberately set at
idea-creation time rather than left as the schema default. Bucket 2 is
the only path that intentionally leaves the schema default — a missing
event on the blocker path is the desired behavior.

5. **Bucket 1, `mutation_intent="apply"` — emit the topology-keyed
   retire-AC clause.** When bucket 1 lands a declared payload with
   `mutation_intent="apply"` and one or more `migration_modules`, the
   spec must carry an explicit retire-the-module acceptance criterion
   whose timing matches the project's install topology (per `AGENTS.md`
   `## Cutover-ticket AC wording`). Read the topology and generate the
   right clause automatically — the operator does not hand-author this.
   See [`body-and-sync-functions.md`](body-and-sync-functions.md) under
   "Retire-AC clause" for the full topology + payload recipe; the
   addendum lands through the
   `items.structured_field.section_append` function call (heading
   `Acceptance Criteria`) so the rest of the spec body is preserved.

## 9. Persist Browser QA Metadata

Every new item gets its inferred `browser_qa_metadata` object written to the DB before body sync. Non-browser tickets use the explicit negative object — `null` or empty string is not permitted.

Route the write through the same structured-field function call as
`spec` so validation, event emission, and rebuild semantics all apply:
dispatch `items.structured_field.replace` with
`payload = {field: "browser_qa_metadata", content: <_browser_qa_metadata_json>, source: "idea"}`
(see [`body-and-sync-functions.md`](body-and-sync-functions.md)).

The validator at
`yoke_core.domain.browser_qa_metadata.validate_json_string` runs
inside the handler. A malformed or contradictory object rejects the
write entirely; investigate the failure and re-run `infer-and-create.md`
step `g` before retrying. Do NOT fall back to writing the raw JSON via
ad-hoc SQL.

## 9b. Path-Claim Required

Every new issue or epic MUST carry either a non-terminal path claim with declared coverage OR a non-terminal `mode='exception'` row with a non-empty `exception_reason`. Item-driven registers land `owner_kind='item'` automatically; the registering session is recorded as provenance (`registered_by_session_id`), never authority. The catch-up audit (`yoke_core.domain.path_integrity_invariants_claim_coverage.check_path_claim_coverage`) and the per-item gate (`yoke_core.domain.path_claim_required_gate.evaluate`) read the same condition; idea calls the gate inline so the operator knows immediately whether creation is complete.

### Decide the claim shape

Use the simplest form that matches reality:

| Situation | Claim shape |
|---|---|
| Item edits one or more files that already exist | `register --paths a.py,b.py` (default `--mode exclusive`, no `--allow-planned` flag needed) |
| Item adds new files that do not yet exist | `register --paths runtime/new_module.py --allow-planned` (mints planned `path_targets` rows attributed to the item) |
| Item legitimately touches no repo surface (validation-only, evidence-only, meta) | `register --mode exception --reason "<concrete justification>"` |

### Register the claim

Dispatch `claims.path.register` (envelope in
[`body-and-sync-functions.md`](body-and-sync-functions.md)) with
`target = {kind: "item", item_id: <id>}` and one of these payload
shapes:

- Existing files only: `{item_id, paths: ["file1.py", "file2.py"],
  mode: "exclusive"}`. Omit `integration_target` to default to the
  project trunk; pass it explicitly only when gating against a
  non-trunk branch.
- Includes future files: same payload plus `allow_planned: true` (mints
  planned `path_targets` rows attributed to the item).
- No-claim exception: `{item_id, mode: "exception", exception_reason:
  "<concrete justification>"}`.

### What to do if registration fails

When `claims.path.register` returns `success=false` (vague coverage,
overlap with an active claim, schema not yet migrated), follow the
canonical resolution protocol at
`.agents/skills/yoke/idea/path-claim-blocking.md`. Workflow: first
classify the overlap via `yoke claims path coordination-decision-build`; for
independent same-file edits author `--gate-point coordination_only`
(compatible overlap, no lifecycle gate); for order-dependent edits author
explicit `--gate-point activation` with directional rationale; fall
back to `--upstream-claim-id` pin, `mode="exception"`, or last-resort
item-level block via `items.scalar.update` on the `blocked` field
(see your `items` packet stanza for the column) only when none of those
fit (do NOT mutate `status` to `'blocked'`).

Roll-back is acceptable only before any GitHub issue has been synced. The forbidden state is a normal synced issue at `status='idea'` / `status='refined-idea'` with zero claim, no exception, and the item-level `blocked` field unset (see your `items` packet stanza) — the catch-up audit surfaces it and refine refuses to advance it past `refining-idea`.
### Verify before exiting idea

After registering, confirm coverage by running the gate:

```bash
yoke claims path required-gate YOK-{id-number}
```

`verdict=pass` means coverage is satisfied; the item is ready to leave the idea workflow. `verdict=block` surfaces a remediation `reason` — read it and amend the claim before continuing.

## 10. Sync Body To GitHub

Before syncing, seed the default unit-test QA requirement for non-browser
issue tickets. This is idempotent and no-ops for browser-testable items or
items that already have an AC verification requirement:

```bash
yoke qa requirement auto-create-for-item --item YOK-{id-number}
```

`yoke qa requirement auto-create-for-item --help` documents the worked example, outcome vocabulary, and flag matrix.

If step 8 wrote body content, push it to the linked GitHub issue via
the `items sync-body` CLI — this is the explicit GitHub-side-effect
sync surface; the `github.body.sync` function-call dispatch is a
follow-up. For now this CLI is the explicit retained-boundary
surface for "rendered body → GitHub issue body":

```bash
# Retained-boundary: explicit GitHub body sync.
yoke items github-sync YOK-{id-number}
```

Skip this step only if the user explicitly declined to add a
description and the item remains title-only. The metadata write in
step 9 intentionally does not post a GitHub status comment, does not
modify labels, and does not trigger a GitHub body resync — the
rendered body excludes `browser_qa_metadata` so the body hash stays
stable across metadata edits.

## 10b. Pre-Handoff Readiness Check

The draft claim acquired in `infer-and-create.md` 5b **stays held** until
readiness passes. Run the check before any release:

```bash
yoke readiness check {id-number}
```

* **`verdict=pass`** — readiness passed; proceed to section 10c and release the draft claim, then display the creation confirmation.
* **`verdict=block`** — print the structured remediation block, **leave the draft claim held**, leave the item at `idea` (do NOT print "next step: /yoke refine"), and surface the remediation so the operator can fix the artifact before refine sees it. Do NOT call `claims.work.release` on the failure path — the held claim is the live-race fix; releasing it on a failed artifact lets a second harness's `yoke sessions offer` route `/yoke refine` against the unfinished spec.

The check runs three validations:

* Every `module.function_name` reference in the spec resolves to a real `def function_name`.
* File Budget records current `wc -l` for every existing-file edit target, and any file >=330 lines has a sibling-module plan.
* File Budget and path-claim coverage agree on which files this ticket touches (the single-validated-step invariant — see section 9b for the authoring rule).

**Gate classification: `repair-before-block`.** Idea-time readiness is advisory in scope (it surfaces gaps but does not mutate path claims itself) and **blocking in ordering** (the draft claim cannot release until the check passes). The mandatory repair pass is at `/yoke refine` entry, where the readiness handler distinguishes recoverable claim-coverage codes (`FILE_BUDGET_NOT_IN_CLAIM`, `CLAIM_NOT_IN_FILE_BUDGET`) from unrecoverable ones and routes recoverable cases to `claims.path.widen` / `claims.path.amend` — or, when explicit removal is appropriate, the operator-debug surface `path-claims narrow --keep-paths <kept>` — rather than releasing the work claim. The idea-time check stays declarative; refine is the first place where the spec is settled enough for safe automatic widening.

Remediation is **advisory at idea-time** — the operator can override with `--skip-readiness-check` (recorded in the audit trail) — but **mandatory at refine-time entry**. The release-only-on-pass ordering is NOT overridable by `--skip-readiness-check`; an override produces a passing check (and therefore a clean release) without bypassing the order.

## 10c. Release The Draft Claim (Layer 1)

Only reachable when section 10b returned exit 0. Release the draft claim acquired in `infer-and-create.md` 5b via the `claims.work.release` function call: `target = {kind: "claim", claim_id: <id>}` plus `payload = {claim_id: <id>, reason: "idea-complete"}`. The `claim_id` comes from the response of the prior `claims.work.acquire` call. `idea-complete` is the canonical idea→refine handoff intent; the release path canonicalizes it through `_RELEASE_REASON_SCHEMA_MAP` to the schema-enum value `handed_off` for storage, preserves the original intent on the `WorkReleased` event as `release_reason_intent`, and emits `IdeaClaimHeld` (duration, claim_id, original `draft-in-progress` claim intent) for observability.

Skip on error / `--dry-run`; the Layer 2 frontier guard keeps title-only rows out of `runnable` regardless.
