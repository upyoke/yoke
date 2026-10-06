# Shepherd: Boss Verdict Result Handling and Post-Verdict Steps

Covers steps 5j, 5l, and 5m: verdict result routing (READY/CAVEATS/NOT_READY), post-verdict deployment flow extraction, and post-verdict QA requirement seeding.

**Inherited from router/boss-verdict.md:** `_num`, `_transition`, `_attempt`, `_session_id`, `_worker_name`, `_verdict`, `MAX_ATTEMPTS`.

---

## 5j. Handle Verdict Result

**READY:**
- Update item status to the target of this transition.
- Render and update Shepherd Log (step 6 in the router).
- Proceed to next transition.

**CAVEATS:**
- Complete the Caveat Resolution Gate (step 5i in `boss-verdict-rubric.md`) first -- all caveats must be RESOLVED, DEFERRED, or ANALYZED.
- Update item status to the target of this transition (CAVEATS is a pass with notes).
- Render and update Shepherd Log (step 6 in the router).
- The caveats will be injected into the next worker's prompt (step 5c in the router).
- Proceed to next transition.

**NOT_READY:**
- Increment the attempt and automatically retry with the Boss feedback while
  `_attempt < MAX_ATTEMPTS`. Preserve failed-review evidence.
- At the attempt limit persist BLOCKED, name the failed gate and recovery,
  and stop. Operator decisions or waivers use their real authority surfaces;
  there is no automatic force-pass.

**Status target:** `_target_stage` is this edge's declared target. Refresh the
item status. If already there (the early planning stamp), verify the edge's
review and continue. Otherwise dispatch `lifecycle.transition.execute` with
`target = {kind: "item", public_ref: $_item_ref}` and
`payload = {source_status: _source_stage, target_status: _target_stage}`.
Refusal stops with its named reason and recovery. Re-read to verify success;
never advance through another skill or substitute a literal stage id.

**Task plan completion:** After the final review edge succeeds, cascade tasks
still in task status `planning` to task status `plan-drafted` through
`workflow_item.epic_task.update_status`. These are the task-owner's statuses,
not parent workflow stage ids. Read the task list once and update each
eligible task; failures stop with the affected task and recovery named.

---

## 5l. Post-Verdict Deployment Flow Extraction (plan-production edge)

After a successful the plan-production edge verdict (READY or CAVEATS) and status update, extract the deployment flow from the spec and write it to the `deployment_flow` column.

This step fires **only** when:
- `_transition` is the plan-production edge
- `_verdict` is `READY` or `CAVEATS`

If either condition is not met, skip this step entirely.

```bash
if [ "$_transition" = "$_plan_transition" ] && { [ "$_verdict" = "READY" ] || [ "$_verdict" = "CAVEATS" ]; }; then
 # Read spec silently
 _dod_spec=$(yoke items get "$_item_ref" spec 2>/dev/null)
 # Fallback to body for non-migrated items
 if [ -z "$_dod_spec" ]; then
 _dod_spec=$(yoke items get "$_item_ref" body 2>/dev/null)
 fi
 # FR-5: Re-read guard — if empty, retry once after 1s (defense-in-depth layer 3)
 if [ -z "$_dod_spec" ]; then
 echo "WARNING: spec read returned empty for $_item_ref in deployment flow extraction — retrying after 1s" >&2
 sleep 1
 _dod_spec=$(yoke items get "$_item_ref" spec 2>/dev/null)
 if [ -z "$_dod_spec" ]; then
 _dod_spec=$(yoke items get "$_item_ref" body 2>/dev/null)
 fi
 if [ -n "$_dod_spec" ]; then
 echo "RECOVERED: spec re-read succeeded for $_item_ref in deployment flow extraction" >&2
 fi
 fi

 # Extract flow ID from Definition of Done section
 # Match field-style lines only: "- **Flow:**", "**Flow:**", or "Flow:" at start of line
 # Anchored to avoid matching prose that happens to contain "flow:"
 _extracted_flow=$(printf '%s' "$_dod_spec" | sed -n '/^## Definition of Done/,/^## /p' | grep -i '^[[:space:]]*-\{0,1\}[[:space:]]*\*\{0,2\}Flow\*\{0,2\}:' | head -1 | sed 's/.*: *//;s/\*//g;s/^ *//;s/ *$//')

 # Discard spec immediately
 unset _dod_spec

 if [ -n "$_extracted_flow" ]; then
 # Validate the flow ID exists in the deployment_flows table
 _flow_exists=$(yoke deployment-flows get "$_extracted_flow" id 2>/dev/null || true)
 if [ -n "$_flow_exists" ]; then
 yoke items scalar update "$_item_ref" --field deployment_flow --value "$_extracted_flow"
 echo "Deployment flow set: $_extracted_flow for $_item_ref"
 else
 echo "WARNING: Extracted flow ID '$_extracted_flow' not found in deployment_flows table. Skipping deployment_flow update."
 fi
 else
 echo "NOTE: No deployment flow found in Definition of Done section for $_item_ref. Skipping deployment_flow update."
 fi
fi
```

**Graceful degradation:** If the `## Definition of Done` section is missing, or the `Flow:` field is absent, or the flow ID does not match any known flow, the extraction silently skips. No error is raised -- the deployment flow can be set manually later.

---

## 5m. Post-Verdict QA Requirement Seeding (plan-production edge)

After a successful the plan-production edge verdict (READY or CAVEATS) and status update, seed initial `qa_requirements` rows for the item. This ensures every epic has explicit QA requirements before implementation begins.

This step fires **only** when:
- `_transition` is the plan-production edge
- `_verdict` is `READY` or `CAVEATS`

If either condition is not met, skip this step entirely.

```bash
if [ "$_transition" = "$_plan_transition" ] && { [ "$_verdict" = "READY" ] || [ "$_verdict" = "CAVEATS" ]; }; then
 # Resolve _qa_verification_stage from the first stage after this binding
 # with board_bucket=reviewing and gate qa_verification. Absence stops with
 # shepherd_qa_anchor_unavailable; publish a definition with that review gate.
 # 1. Read ACs from spec (silently pattern)
 _qa_seed_spec=$(yoke items get "$_item_ref" spec 2>/dev/null)
 if [ -z "$_qa_seed_spec" ]; then
 _qa_seed_spec=$(yoke items get "$_item_ref" body 2>/dev/null)
 fi

 # 2. Extract AC lines
 _qa_seed_acs=$(printf '%s' "$_qa_seed_spec" | sed -n '/^## Acceptance Criteria/,/^## /{ /^## /d; p; }')

 # 3. Seed one qa_requirement per testable AC
 _qa_ac_count=0
 printf '%s\n' "$_qa_seed_acs" | while IFS= read -r _ac_line; do
 # Match lines like "- [ ] AC-1: description" or "- [ ] description"
 case "$_ac_line" in
 *'- [ ] AC-'*|*'- [ ] '*)
 _ac_desc=$(printf '%s' "$_ac_line" | sed 's/^.*\- \[ \] //')
 yoke qa requirement add \
 --item "$_item_ref" \
 --qa-kind "ac_verification" \
 --qa-phase "verification" \
 --workflow-transition "$_qa_verification_stage" \
 --blocking-mode "blocking" \
 --requirement-source "ac_derived" \
 --success-policy "$_ac_desc" >/dev/null 2>&1 || true
 _qa_ac_count=$((_qa_ac_count + 1))
 ;;
 esac
 done

 # 4. If no ACs found, seed at least one implementation review requirement
 _qa_existing_count=$(yoke db read --format lines "SELECT COUNT(*) FROM qa_requirements WHERE item_id=(SELECT item_id FROM item_refs WHERE public_ref='$_item_ref')" 2>/dev/null) || true
 if [ -z "$_qa_existing_count" ] || [ "$_qa_existing_count" = "0" ]; then
 yoke qa requirement add \
 --item "$_item_ref" \
 --qa-kind "implementation_review" \
 --qa-phase "verification" \
 --workflow-transition "$_qa_verification_stage" \
 --blocking-mode "blocking" \
 --requirement-source "seeded_default" \
 --success-policy "Implementation matches the item spec" >/dev/null 2>&1 || true
 fi

 echo "QA: Seeded requirements for $_item_ref at $_transition"
 unset _qa_seed_spec _qa_seed_acs _qa_batch_payload
fi
```

**Behavior notes:**
- Seeding is idempotent per-requirement-source: duplicate calls create additional rows (harmless since each run is tracked independently). The `requirement_source=ac_derived` and `requirement_source=seeded_default` values distinguish shepherd-seeded requirements from manually-added ones.
- If the item has no ACs (title-only), a single `implementation_review` requirement is seeded as a fallback.
- Browser, command, and machine cases come from attached project QA plans or
  explicit method-backed requirements. This AC seeding step does not infer or
  duplicate them.
- Errors during seeding are swallowed (`|| true`) — QA seeding should never block the shepherd pipeline.
