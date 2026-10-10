# Shepherd — conditional PM and design gates

## PM gate

Run readiness.prd_validate; exit 0 (PASS/WARN-only) skips PM, warnings remain
context. Exit 1 invokes PM. Other exit/read refusal stops with named recovery.

```bash
yoke readiness prd-validate "$_item_ref"
```

PM/Designer are Read, Grep, Glob only (no Bash, no DB packet). Parent captures
authoritative spec, body only if empty, as rollback baseline and a full stable
per-dispatch file. Separate operator instructions from stored field data;
never persist rendered instruction wrappers back into spec.
Use original _item_ref, never synthesize public ref from internal _num.

Scratch helper owns YOKE_SCRATCH_ROOT/machine temp_root/OS fallback.
Path is unique by original item ref/session/attempt:

```bash
_pm_input_dir=$(yoke scratch dispatch-inputs "$_item_ref" "$_session_id" "$_attempt")
_pm_input_path="${_pm_input_dir}/product-manager-spec.md"
printf '%s' "$_pre_pm_spec" >"$_pm_input_path"
```

_pre_pm_context_block names the file, source and complete length:

```text
Your input ${_pre_pm_source} for ${_item_ref} is at ${_pm_input_path}.
MUST Read it first; do not rely on any inline copy.
If the path is unreadable, report it and stop from that premise.
Preserve every inherited section, operator decision, AC, refinement and addendum
intact. Enrich missing/incomplete PRD only; no deletion, reordering or rewriting.
Return complete inherited-plus-added spec.
```

Use registered deployment-flows inventory for the item's project; if readable,
give actual IDs/project/descriptions. DoD chooses existing project/flow/rationale,
internal doc/script route vs service restart/release appropriate to that project.
Failed inventory read is named, never swallowed or replaced by guessed routes.

Dispatch product-manager through DispatchDescriptor/render_for_harness; prompt:

```text
 Write a structured spec for backlog epic PREFIX-{N}.
 Title: {_title}; original ref: {_item_ref}; repository: {MAIN_ROOT}.
 Read, Grep, Glob only. MUST Read the named file first;
 do not rely on any inline copy. Unreadable input: report and stop.
 Do not attempt to run DB or Bash commands.
 {_pre_pm_context_block if non-empty}
 {current caveats, Scholar context and project-flow guidance}
 Attempt {_attempt} of {MAX_ATTEMPTS}; {prior Boss feedback on retry}.
 Required: ## Problem Statement (>=20 substantive characters), ## Goals
 (a measurable bullet), ## Requirements (testable functional requirement),
 ## Success Metrics (concrete measures), ## Acceptance Criteria
 (- [ ] AC-{N}: independently testable checks aligned to requirements).
 Any deferral: ## Deferred Items table | Description | Reason | Work item |
 with UNFILED until actually filed.
 Include ## Definition of Done with Project, Flow, Rationale before verdict sections.
 Return complete spec; no file writes.
```

Capture the PM's output as `_worker_output`.
Empty/no spec heading: one deliverable-only resume, no more exploration, return
complete spec as first action. Still empty/headingless: NOT_READY; no loop.
Strip ---REFLECTION-START--- through ---REFLECTION-END--- before persistence.

If baseline >200 bytes and output <60% of baseline, set
_pm_destructive_rewrite=1, preserve baseline and NOT_READY **without writing**.
No restore needed because output never landed. The guarded branch is:

```bash
_pm_write_allowed=0
if [ "${_pm_destructive_rewrite:-0}" != "1" ]; then
 _pm_write_allowed=1
fi
```

Only allowed output goes through items.structured_field.replace, spec,
source shepherd, original public-ref target. Readback must be nonempty,
contain a spec heading (Problem/Goals/Requirements/Functional Requirements)
and >=200 bytes. Empty read: retry once after 1s. Failed verification: up to
two write retries, each readback; if still failed and baseline >200, restore
baseline through the sanctioned guarded force option, then NOT_READY.
No advance on unverifiable output. Resume PRD precheck naturally skips a valid
already-written spec; PM is not a Boss verdict.

## Design gate

Read design_spec. Existing nonempty design skips and persists Designer SKIPPED.
Otherwise judge actual interactive UI/UX benefit: significant screens/forms/
navigation/modals/dashboard/data visualization/layout merits design.
Backend/schema/CI/infra/internal-tool/skill/doc work and markdown boards do not,
even when prose contains table/interface/view/list/display/dashboard homonyms.
Log one-sentence INCLUDE/SKIP rationale; SKIPPED satisfies only Designer.

```bash
yoke items get "$_item_ref" design_spec
yoke shepherd verdict --item "$_item_ref" --transition "$_transition" --worker "$_worker_name" --verdict SKIPPED --caveats "{design skip rationale}"
```

If included, parent captures full spec/body with the same rollback/source rules:

```bash
_pd_input_dir=$(yoke scratch dispatch-inputs "$_item_ref" "$_session_id" "$_attempt")
_pd_input_path="${_pd_input_dir}/product-designer-spec.md"
printf '%s' "$_pre_designer_spec" >"$_pd_input_path"
```

_pre_designer_context_block:

```text
Your input ${_pre_designer_source} for ${_item_ref} is at ${_pd_input_path}.
MUST Read first; do not rely on any inline copy.
If the path is unreadable, report it and stop from that premise.
Base complete design on this input; no DB/Bash refetch.
```

Dispatch product-designer through the same descriptor renderer:

```text
 Create a UX/design spec for PREFIX-{N}.
 Title: {_title}; original ref: {_item_ref}; repository: {MAIN_ROOT}.
 Read, Grep, Glob only. MUST Read the named file first;
 do not rely on any inline copy. Unreadable: stop and report.
 Do not attempt to run DB or Bash commands.
 {_pre_designer_context_block if non-empty}
 {prior caveats}; attempt {_attempt}/{MAX_ATTEMPTS}; {prior Boss feedback}.
 Return complete design spec; no files.
```

Write the Designer's output to the `items.design_spec` structured field.
Use items.structured_field.replace with source shepherd; body rerender is
handler-owned. success=false is NOT_READY, named failed field/recovery,
STOP without advancing. [Plan](plan-handoff.md) follows.
