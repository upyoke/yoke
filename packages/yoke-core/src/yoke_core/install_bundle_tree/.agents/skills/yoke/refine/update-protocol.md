# /yoke refine — Update Protocol

Extracted from `SKILL.md`. Contains steps 6-12 — apply improvements, verify writes, advance status, release claims, and final output.

The function-call envelope shape and per-family recipes referenced below
live in
[`../idea/body-and-sync-functions.md`](../idea/body-and-sync-functions.md).

---

### 6. Apply Improvements (Additive Only)

For each recommended change, **enhance** the existing content — do not replace it. The approach is:

1. **Read the existing content** from the structured field via the
   `items.get.run` function call (`fields: ["<field>"]`).
2. **Identify gaps** from the critique (missing ACs, missing blast-radius, missing error handling, etc.).
3. **Append** new sections, ACs, discovery commands, and analysis to the existing content.
4. **Edit in place** for grammar/clarity fixes only — no meaning changes, no paraphrasing, no abstraction.
5. **Write the enhanced version** back through the function-call dispatcher.

**Two write surfaces, one rule each.**

- **Additive transform (preserve existing field, add a heading-led block):**
  dispatch `items.structured_field.append_addendum` with `target = {kind:
  "item", item_id: N}` and `payload = {field, heading, content, source:
  "refine"}`. The handler reads the current field through canonical DB
  routing, applies an idempotent `## heading`-led append, writes through
  the existing guarded structured-write path, and re-reads to verify. It
  refuses empty content, preserves shrinkage/freeze/empty guards, and
  returns evidence the success summary can quote.
  Operator/debug adapter: `printf '%s\n' "<addendum>" | yoke items structured-field append-addendum YOK-N --field spec --heading "..." --source refine --stdin`.
- **Full field rewrite (you authored the entire intended content):**
  dispatch `items.structured_field.replace` with `payload = {field,
  content, source: "refine"}`. Keep skill examples replace-first for
  full rewrites. **Never** read the field via `items.get.run`, transform
  via shell choreography, and pipe the result back into another write —
  the PreToolUse Bash lint catches that pattern and the remediation
  points to the addendum / section-upsert / section-append handlers
  above. Bypass token: `# lint:no-structured-transform-check` (audited).
  Operator/debug adapter: `printf '%s\n' "<full field content>" | yoke items structured-field replace YOK-N --field spec --source refine --stdin`.

Raw `items.body` writes are unsupported — body is a virtual rendered
field, always go through a structured field or `item_sections` (via
`items.section.upsert`).

Use repo-root-resolved script paths in every shell command; do not rely
on shell variables persisting across separate tool invocations.

The enhanced artifact must encode the mandatory-check findings from
step 5. Do not stop at cleaner wording if the artifact still lacks
verified references, blast-radius discovery, cleanup coverage,
failure/recovery coverage, or resolved issue-level open questions.

**Subtraction detection check (mandatory before writing).** Before
writing any field, diff the enhanced content against the original. If
ANY original content is missing or materially changed in meaning —
decisions, ACs, user questions, evidence, observations, numbered items
— the write is rejected. Add the missing content back before writing.
This check exists because refine can silently destroy operator-provided
content by abstracting it into vague prose.

**Escalation gate.** If the critique identified major errors (wrong
references verified against the codebase, contradictory requirements,
scope conflicts with active tickets), do NOT dispatch the write.
Instead, stop and surface the issues to the operator. Do NOT advance
status. The item stays at `refining-idea` or `refining-plan` until the
operator resolves the issue.

**File Budget escalation.** If the ticket is implementation-bearing AND
the File Budget cannot be resolved during this refine pass — the file
shape is genuinely unknown, the touched source files are already over
the 300-line design target with no obvious split, or a proposed task
owns multiple responsibilities that cannot be reduced without operator
input — do NOT silently advance. Surface the blocker to the operator
with the exact set of files in question (including current line counts)
and the resolution options (split before implementation, expand the
budget with justification, descope, or split the ticket). The item
stays at `refining-idea` (issue) or `refining-plan` (epic) until the
operator resolves it.

**Obvious File Budget repair.** Do not escalate when reference
verification finds one obvious live owner for the missing path and adding
that path does not change the project, deployment target, or behavior
scope. Add the verified file to the File Budget, widen the path claim
with the evidence-backed reason, and continue refinement. Escalate only
when there are multiple plausible owners, the repair would change scope,
or the overlap/dependency decision is genuinely ambiguous.

Field routing (dispatch `items.structured_field.replace` with
`payload.field` matching the routing below):

- Spec content (problem, scope, ACs, dependencies, likely files) → `spec`
- Design content (UX flows, edge cases) → `design_spec`
- Technical plan content → `technical_plan`
- Worktree plan content → `worktree_plan`
- Caveat content → `shepherd_caveats`
- Long-running execution context → the `Progress Log` section via the
  `items.progress_log.append` function call (`target = {kind: "item",
  item_id: N}`, `payload = {headline, content, source: "refine"}`).
  The handler creates the section if missing, appends after existing
  content if present, and formats the
  `## <UTC ISO timestamp> entry — <headline>` header itself. Never read
  the section via shell, transform in shell, and pipe back through
  `items.section.upsert` — that pattern is caught by the
  structured-transform lint and the remediation now points at
  `items.progress_log.append`.
  Operator/debug adapter: `printf '%s\n' "<entry body>" | yoke items progress-log append YOK-N --headline "..." --source refine --stdin`.

AC rules:

- When ACs exist but lack canonical `AC-N:` labels, normalize them to
  `- [ ] AC-N: {description}` during the refinement pass.
- When ACs are missing entirely, add an `## Acceptance Criteria` section
  with appropriate ACs derived from the item's stated requirements.
  This is part of the normal rewrite — not a separate pass.

### 7. Verify The Writes

After every write, re-read the updated field via the `items.get.run`
function call (`fields: ["<field>"]`) and confirm it contains the
intended result. If the field comes back empty or malformed, retry the
write once before reporting failure. Always re-read live DB state
before concluding that a structured-write or status-advance step
stopped short — the write may have succeeded even if the response was
unclear.

Also sanity-check that the persisted content still includes the
structural changes you intended: canonical AC labels, any required
grep/residue guidance, explicit cleanup/removal notes, and
failure/recovery coverage where applicable.

### 8. Capture Final Summary

Before status advancement, capture the details you will present after cleanup is finished. Do not emit the success summary yet:

```
## Refinement Complete — YOK-{N}

**Fields updated:** {list of fields written}
**Changes applied:** {count}

{Brief summary of what changed and why}
```

### 9. Advance Status on Success

After all refinement work is verified complete, advance status based on
the entry phase determined in step 1b. Dispatch the
`lifecycle.transition.execute` function call with `target = {kind:
"item", item_id: N}`.

**Idea refinement** (entry was `idea` or `refining-idea`): advance to
`refined-idea`. Payload: `{target_status: "refined-idea",
source_status: "refining-idea"}`. Final output should include:

> **YOK-{N}** refined: `refining-idea` -> `refined-idea`
> The scheduler will route this item to `/yoke shepherd` (epic) or `/yoke advance` (issue) for implementation.

**Plan refinement** (entry was `refining-plan`, epic only): advance to
`planned`. Payload: `{target_status: "planned", source_status:
"refining-plan"}`. Final output:

> **YOK-{N}** plan refined: `refining-plan` -> `planned`
> The scheduler will route this item to `/yoke conduct` for implementation.

GitHub body sync runs implicitly on the lifecycle transition; explicit
re-sync is not required.

**If any step above failed:** Do NOT advance status. Leave the item at
its current status (`refining-idea` or `refining-plan`) and report the
failure.

**If the advance fails with `GATE_DB_CLAIM_PROSE_MISMATCH`:** the
spec/body declares governed DB mutation but the stored
`db_mutation_profile` is still `{"state":"none"}` and no reviewed-none
`DbClaimAmended` event is on record. Dispatch `db_claim.amend` before
retrying the advance:

- **Ticket actually mutates the governed DB** — `target = {kind: "item",
  item_id: N}`, `payload = {reason: "refine: prose declares governed
  DB mutation", claim: <unified-claim-json>}`.
- **Meta-ticket about DB governance** — the spec legitimately cites
  `ALTER TABLE`, `ADD COLUMN`, `migration_audit`, or similar while
  performing no governed mutation. Dispatch with `payload = {reason:
  "refine: ticket discusses DB governance vocabulary but mutates
  nothing; reviewed-none", claim: {state: "none"}}`. The amendment
  emits a `DbClaimAmended` event; the prose-vs-claim gate honors the
  latest event with `context.new_profile.state="none"` and
  `context.validation_result="pass"` and clears structural DDL-shape
  hits on the next advance attempt. Do **not** work around the gate by
  backtick-wrapping DDL verbs or deleting governance terminology from
  the spec.

The declared payload combines profile and attestation fields in one
flat object; `migration_strategy` is required when
`mutation_intent="apply"`, and `pre_merge_readers_writers[].role` is
only `reader` or `writer` (schema-changing migration modules use
`writer`). See [.yoke/docs/db-reference.md](../../../../.yoke/docs/db-reference.md).
Once the amendment lands, retry the `lifecycle.transition.execute` call.
Operator/debug adapter: `yoke db-claim amend`
constructs the same `db_claim.amend` request envelope.

### 10. Release Item Claim

Release the exclusive work claim before any success output is emitted
via the `claims.work.release` function call: `target = {kind: "claim",
claim_id: <claim_id>}` plus `payload = {claim_id: <claim_id>, reason:
"completed"}`. Resolve the `claim_id` via the
`claims.work.holder_get` read against the current item (or remember
it from the matching `acquire` response).

This MUST run before the final operator summary. A release failure
still needs to be called out in the final report; do not silently
swallow it.

### 11. Final Output

After status advancement and claim release, emit:

```
## Refinement Complete — YOK-{N}

**Fields updated:** {list of fields written}
**Changes applied:** {count}

{Brief summary of what changed and why}
```

Include the applicable status transition note from step 9.

### 12. Completion

Refinement is complete when:
- All non-empty artifacts have been evaluated
- Identified issues have been addressed in the appropriate structured fields
- Every updated field has been re-read successfully after the write
- Status has been advanced to `refined-idea` (idea refinement) or `planned` (plan refinement)
- The item claim has been released with reason `completed`
- The operator has been shown what changed in the final output

Refinement is NOT complete if:
- Artifact reads failed (DB error) — report the error and stop
- The operator interrupted with a question — answer it before continuing
