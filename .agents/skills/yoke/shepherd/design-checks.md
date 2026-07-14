# Shepherd: PM Spec Gate and Design Gate

Covers steps 5a and 5b: PM spec-writing gate (conditional) and design gate (conditional), plus Designer invocation when the design gate fires. Both gates apply during `refined_idea_to_planning`.

**Inherited from router:** `MAX_ATTEMPTS`, `_num`, `_type`, `_title`, `_item_status`, `_epic`, `_scholar_context`, `_prior_caveats`, `_transition`, `_attempt`, `_session_id`, `_worker_name`.

---

## 5a. PM Spec-Writing Gate (conditional, evaluated during `refined_idea_to_planning`)

Items arrive at shepherd at `refined-idea` (refined via `/yoke refine`). The refine skill improves the idea but does not write the structured PRD sections required by the Architect's PRD validation gate. The PM spec-writing gate ensures a structured spec exists before the Architect is invoked.

**Pre-check: Run PRD validator silently.** This registered read-only
readiness gate dispatches through the Yoke function-call transport.

```bash
yoke readiness prd-validate "YOK-$_num" >/dev/null 2>&1
_prd_precheck_rc=$?
```

If exit code is 0 (PASS or WARN-only), skip the PM. Log: `PM spec gate: SKIP — PRD validation already passes for YOK-{N}`. Proceed to Design Gate (step 5b).

If exit code is 1 (FAIL), invoke the PM.

**Pre-write spec snapshot to a file-backed input path.** Before invoking the PM, capture the current spec in a shell variable as a rollback baseline AND write it to a stable per-dispatch file that the PM Reads as its single canonical input. The Product Manager is `Read, Grep, Glob` only (no Bash, no DB packet); the orchestrator owns the DB read and hands PM a path to Read. The inline-embed shape is intentionally avoided — a single source of truth eliminates the "truncated inline copy while the prose still claims full embedding" failure mode.

```bash
_pre_pm_spec=$(yoke items get $_num spec)
if [ -z "$_pre_pm_spec" ]; then
 _pre_pm_spec=$(yoke items get $_num body)
 _pre_pm_source="body"
else
 _pre_pm_source="spec"
fi
_pre_pm_len=${#_pre_pm_spec}
```

Write the inherited content to a stable per-dispatch file path under the helper-resolved scratch root (`YOKE_SCRATCH_ROOT`, machine-config `temp_root`, or OS temp fallback). The path is unique per dispatch (item id + session id + attempt) so a stale file from a prior dispatch can never be silently consumed. Build a `_pre_pm_context_block` that names the absolute path as the PM's single canonical input — no inline data fence:

```bash
_pre_pm_context_block=""
_pm_input_path=""
if [ "$_pre_pm_len" -gt 0 ]; then
 _pm_input_dir=$(yoke scratch dispatch-inputs "YOK-${_num}" "${_session_id}" "${_attempt}")
 _pm_input_path="${_pm_input_dir}/product-manager-spec.md"
 printf '%s' "$_pre_pm_spec" >"$_pm_input_path"
 _pre_pm_context_block="
## Existing item context (read the input file before authoring)

Your input ${_pre_pm_source} for YOK-${_num} is at ${_pm_input_path} (${_pre_pm_len} bytes).
You MUST Read that file as your first action before authoring. Do not rely on any inline copy — the dispatch prompt does not embed the inherited content. If the path is unreadable for any reason, report the path and stop from that premise rather than authoring from memory or a partial copy.

This existing content is substantive (${_pre_pm_len} bytes). PRESERVE it intact and ENRICH it additively: keep every existing section, operator decision, AC, and prior refinement, then fill in only the PRD sections that are missing or incomplete. Do not delete, re-order, or rewrite existing operator-authored content. Do not strip the addenda blocks (e.g., \`## Refinement Addendum\`). Return the complete spec content with both the inherited material and your additions."
fi
```

**Fetch deployment flows for context:**

```bash
_available_flows=$(python3 -m yoke_core.cli.db_router flows list 2>/dev/null || true)
```

Build flow guidance block if flows are available:

```bash
_flow_guidance=""
if [ -n "$_available_flows" ]; then
 _flow_guidance="
## Deployment Flow Selection

After writing the spec, include a **## Definition of Done** section at the end (before any Shepherd Log/Caveats sections). This section MUST contain a deployment flow selection with these three fields:

- **Project:** {project id, e.g., yoke or buzz}
- **Flow:** {flow id from the list below}
- **Rationale:** {one sentence explaining why this flow fits}

Available deployment flows:
$(echo "$_available_flows" | while IFS='|' read -r fid fproj fname fdesc _rest; do
 printf ' - %s (%s): %s\n' "$fid" "$fproj" "$fdesc"
done)

Choose the flow that best matches the item's deployment needs. For script/doc-only changes, use an internal flow. For changes requiring service restarts, use a deploy flow. For production-facing changes in buzz, use the release or hotfix flow as appropriate.
"
fi
```

**Invoke PM subagent.** The Product Manager is read-only (`Read, Grep, Glob` — no Bash, no DB packet) and cannot fetch DB context itself. The orchestrator already captured the current spec/body into `_pre_pm_spec` in the snapshot step above, wrote it to the stable per-dispatch input path `_pm_input_path`, and built `_pre_pm_context_block` that names that path. The dispatch prompt names the absolute input file path as the PM's single canonical input surface; the prompt does NOT embed the inherited content inline. Do NOT instruct PM to run `db_router`, Bash, or any other DB command.

**Dispatch:** descriptor `DispatchDescriptor(role="product-manager")` rendered via `yoke_core.domain.dispatch_descriptors.render_for_harness(descriptor, harness_id)`. Result-schema markers: `---REFLECTION-START---`. The descriptor's `prompt: |` block is filled with:
```
 Write a structured spec for backlog epic YOK-{N}.
 Title: {_title}
 Type: epic
 Repository root: {MAIN_ROOT}
 Data directory: {MAIN_ROOT}/data (DB, config live here)

 You are read-only (Read, Grep, Glob). The orchestrator has already
 written the existing item content to the input file path named in
 the context block below. You MUST Read that file as your first
 action before authoring; do not rely on any inline copy — the
 dispatch prompt does not embed the inherited content. If the input
 path is unreadable, report the path and stop from that premise
 rather than authoring from memory. Do not attempt to run DB or
 Bash commands.

 The PRD validator will run immediately after your spec is written.

 {_pre_pm_context_block if non-empty}

 {_prior_caveats_block if any}
 {_scholar_context if any}
 {_flow_guidance if non-empty}

 You MUST include the following sections — the PRD validator hard-fails on any
 of these missing. Omitting them causes a wasted round-trip:

 - ## Problem Statement — MUST be present with ≥20 chars of substantive content
 explaining why this work matters.
 - ## Goals — MUST be present with at least one bulleted, measurable goal.
 - ## Requirements — MUST be present with at least one testable functional
 requirement (e.g., 'FR-1: The system shall...').
 - ## Success Metrics — MUST be present defining how we will know this work
 succeeded. Include concrete, measurable criteria.
 - ## Acceptance Criteria — MUST be present with '- [ ] AC-{N}: {description}'
 checkboxes. Each AC must be specific and independently testable, aligned with
 the functional requirements. Conduct requires ACs to verify each item — items
 without ACs will be hard-blocked at the planning_to_plan_drafted gate.

 If you defer any work from scope (e.g., "deferred to a follow-up", "out of scope"),
 you MUST include a ## Deferred Items section with a table tracking each deferral.
 Format: | Description | Reason | Ticket | — mark Ticket as UNFILED until filed.

 Attempt {_attempt} of {MAX_ATTEMPTS}.
 {if _attempt > 1: "Previous Boss feedback:\n{_boss_feedback}"}

 Return the complete spec content. Do not write any files.
```

Capture the PM's output as `_worker_output`.

**Empty output detection and recovery.** Check if `_worker_output` is empty or contains no spec-like headings (`## Problem`, `## Goals`, `## Requirements`, `## Acceptance Criteria`, `## Functional Requirements`):

If the output is empty or has no spec headings:
1. Log: `"WARNING: PM agent returned no spec content for YOK-{N} (likely hit turn limit). Resuming with deliverable-only prompt."`
2. Resume the PM agent with: `"You ran out of turns without producing the spec. Produce the complete spec NOW from whatever context you gathered. Do not explore further — write the spec immediately as your very first action. Return the complete spec content."`
3. Capture the resumed agent's output as the new `_worker_output`.
4. If still empty or has no spec headings, log: `"ERROR: PM agent failed to produce spec after resume for YOK-{N}. Treating as NOT_READY."` and treat as a failed worker output.
5. Cap this resume to exactly 1 attempt — do not loop.

**PM output extraction.** Strip reflection blocks (`---REFLECTION-START---` to `---REFLECTION-END---`) from `_worker_output` before body processing.

**Destructive-rewrite guard.** Before writing PM output to `items.spec`, compare its length to the pre-PM baseline. The dispatch prompt instructs additive enrichment, but the persistence path must refuse the write rather than silently overwrite substantial inherited content when PM ignored the instruction:

```bash
_worker_len=${#_worker_output}
if [ "$_pre_pm_len" -gt 200 ] && [ "$_worker_len" -lt $((_pre_pm_len * 60 / 100)) ]; then
 echo "WARNING: PM output (${_worker_len} bytes) is less than 60% of pre-PM ${_pre_pm_source} (${_pre_pm_len} bytes) for YOK-${_num}. Treating as destructive rewrite — preserving pre-PM baseline and reporting NOT_READY without writing the PM output." >&2
 _pm_destructive_rewrite=1
fi
```

Skip the write when `_pm_destructive_rewrite=1` and treat the PM step as NOT_READY in the router. No restore call is needed because the PM output has not been written.

**Write the PM's spec to `items.spec`** via the
`items.structured_field.replace` function call (envelope in
[`../idea/body-and-sync-functions.md`](../idea/body-and-sync-functions.md)):
when `_pm_destructive_rewrite` is not set, dispatch
`target = {kind: "item", item_id: $_num}`, `payload = {field: "spec",
content: "$_worker_output", source: "shepherd"}`.

```bash
if [ "${_pm_destructive_rewrite:-0}" != "1" ]; then
 # Dispatch items.structured_field.replace with the PM output.
fi
```

**Post-write content verification (hard gate).** Re-read `items.spec` from the DB:

```bash
_verify_spec=$(yoke items get $_num spec)
if [ -z "$_verify_spec" ]; then
 echo "WARNING: spec read returned empty for YOK-$_num in FR-A3 verification — retrying after 1s" >&2
 sleep 1
 _verify_spec=$(yoke items get $_num spec)
 if [ -n "$_verify_spec" ]; then
 echo "RECOVERED: spec re-read succeeded for YOK-$_num in FR-A3 verification" >&2
 fi
fi
```

Verification checks (ALL must pass):
1. `items.spec` is non-empty (length > 0)
2. At least ONE spec heading present: `## Problem`, `## Goals`, `## Functional Requirements`, `## Requirements`
3. Spec length >= 200 bytes

**Fallback on verification failure.** If post-write content verification fails:
1. Retry the `items.structured_field.replace` dispatch up to 2 times.
2. After each retry, re-run the post-write content verification.
3. If all retries fail and the pre-PM spec was substantial (> 200
   bytes), restore it by dispatching
   `items.structured_field.replace` again with `payload = {field:
   "spec", content: "$_pre_pm_spec", source: "shepherd",
   force: true}`. Log:
   `WARNING: PM output could not be verified. Pre-PM spec restored.`
4. Do NOT proceed. Log the failure and treat as NOT_READY.

If verification passes:
- Log: `"VERIFIED: PM spec present in items.spec after write."`
- No temp-file cleanup required; the rollback baseline lives in `_pre_pm_spec`.

**Resume behavior:** The PM step does not produce a Boss verdict. On resume, the prd-validate pre-check naturally handles idempotency — if the PM already wrote the spec, validation passes and the PM is skipped.

---

## 5b. Design Gate (evaluated during `refined_idea_to_planning`)

This gate is conditional. The design gate uses a unified heuristic in both standalone and subagent mode (no user interaction).

**Step 1: Existing design check.** Read the item's canonical structured field:
 ```bash
 _design_spec=$(yoke items get "YOK-$_num" design_spec)
 ```
If `_design_spec` is non-empty, skip design. Log: `Design gate: SKIP -- design already exists for YOK-{N}`. Persist a SKIPPED pseudo-verdict:

```bash
yoke shepherd verdict --item "YOK-$_num" --transition "$_transition" --worker "$_worker_name" --verdict "SKIPPED" --caveats "design gate: existing design"
```

**Step 2: Judgment-based design evaluation.** Read the item title and spec. Answer one question:

> **Does this item involve user-facing UI/UX that would benefit from a design spec?**

A design spec is warranted when the item creates or significantly modifies visual interfaces that users interact with -- screens, forms, dashboards, modals, navigation flows, data visualizations, or layout changes. The Designer subagent will produce wireframes, interaction patterns, and visual specifications.

A design spec is NOT warranted when:
- The item modifies backend logic, shell scripts, DB schemas, or SKILL.md files -- even if the spec mentions terms like "table" (DB tables), "interface" (code contracts), "display" (logging output), "list" (data structures), "view" (DB views), or "dashboard" (board rendering in markdown)
- The item changes internal tooling, CI/CD pipelines, or infrastructure
- The item is documentation-only or process-oriented
- The "UI" is markdown-rendered output (like BOARD.md) rather than an interactive visual interface

**Decision:**

- **Needs design:** Log: `Design gate: INCLUDE -- {one-sentence rationale, e.g., "item creates a new settings form with multiple input fields and validation"}`. Proceed to invoke Designer.
- **Skip design:** Log: `Design gate: SKIP -- {one-sentence rationale, e.g., "item modifies shepherd SKILL.md files, no user-facing UI"}`. Persist a SKIPPED pseudo-verdict as above.

**Resume behavior:** A `SKIPPED` verdict in `shepherd_verdicts` for `refined_idea_to_planning` is treated as equivalent to `READY` for resume purposes in step 4 (in the router).

---

## 5d. Invoke Worker (refined_idea_to_planning -- Designer)

Invoke the Designer. The Product Designer is `Read, Grep, Glob` only (no Bash, no DB packet) — the same read-only contract as the Product Manager (see the PM spec snapshot step above for the rationale). The orchestrator owns the DB read and hands Designer a path to Read. Capture the current spec/body and build a `_pre_designer_context_block` using the same file-backed pattern the PM spec snapshot establishes for `_pre_pm_context_block` (input file under the gitignored scratch root, no inline data fence):

```bash
_pre_designer_spec=$(yoke items get $_num spec)
if [ -z "$_pre_designer_spec" ]; then
 _pre_designer_spec=$(yoke items get $_num body)
 _pre_designer_source="body"
else
 _pre_designer_source="spec"
fi
_pre_designer_len=${#_pre_designer_spec}

_pre_designer_context_block=""
_pd_input_path=""
if [ "$_pre_designer_len" -gt 0 ]; then
 _pd_input_dir=$(yoke scratch dispatch-inputs "YOK-${_num}" "${_session_id}" "${_attempt}")
 _pd_input_path="${_pd_input_dir}/product-designer-spec.md"
 printf '%s' "$_pre_designer_spec" >"$_pd_input_path"
 _pre_designer_context_block="
## Existing item context (read the input file before authoring)

Your input ${_pre_designer_source} for YOK-${_num} is at ${_pd_input_path} (${_pre_designer_len} bytes).
You MUST Read that file as your first action before authoring. Do not rely on any inline copy — the dispatch prompt does not embed the inherited content. If the path is unreadable for any reason, report the path and stop from that premise rather than authoring from memory.

Base the design spec on this item content; do not reach for DB or Bash to refetch it. Return the complete design spec content."
fi
```

**Dispatch:** descriptor `DispatchDescriptor(role="product-designer")` rendered via `yoke_core.domain.dispatch_descriptors.render_for_harness(descriptor, harness_id)`. Result-schema markers: `---REFLECTION-START---`. Do NOT instruct Designer to run `db_router`, Bash, or any other DB command. The descriptor's `prompt: |` block is filled with:
```
 Create a UX/design spec for YOK-{N}.
 Title: {_title}
 Repository root: {MAIN_ROOT}

 You are read-only (Read, Grep, Glob). The orchestrator has already
 written the existing item content to the input file path named in
 the context block below. You MUST Read that file as your first
 action before authoring; do not rely on any inline copy — the
 dispatch prompt does not embed the inherited content. If the input
 path is unreadable, report the path and stop from that premise
 rather than authoring from memory. Do not attempt to run DB or
 Bash commands.

 {_pre_designer_context_block if non-empty}

 {_prior_caveats_block if any}

 Attempt {_attempt} of {MAX_ATTEMPTS}.
 {if _attempt > 1: "Previous Boss feedback:\n{_boss_feedback}"}

 Return the complete design spec content. Do not write any files.
```

Write the Designer's output to the `items.design_spec` structured field.
Use the `items.structured_field.replace` function call
(envelope in
[`../idea/body-and-sync-functions.md`](../idea/body-and-sync-functions.md)):
`target = {kind: "item", item_id: $_num}`, `payload = {field:
"design_spec", content: "$_worker_output", source: "shepherd"}`.
The rendered-body re-sync is part of the handler's side-effect chain.

If the dispatch returns `success=false`, log
`ERROR: structured field write failed for design_spec on YOK-$_num.
STOP -- do not advance status.` and treat as NOT_READY.
