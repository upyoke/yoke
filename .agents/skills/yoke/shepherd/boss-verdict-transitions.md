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
- Increment attempt counter.
- If `_attempt < MAX_ATTEMPTS`:
 - **Standalone mode:** Inform the user of the failure and Boss feedback. Ask whether to retry, force-pass, or abort.
 - **Subagent mode:** Automatically retry -- go back to step 5d (in the transition-specific sub-file) with `_attempt + 1` and `_boss_feedback` included in the prompt.
- If `_attempt >= MAX_ATTEMPTS`:
 - **Standalone mode:** Inform the user. Offer options: (1) retry anyway, (2) force-pass with caveats, (3) abort.
 - **Subagent mode:** Write a BLOCKED verdict and return exit code 1:
 ```bash
 yoke shepherd verdict --item "YOK-$_num" --transition "$_transition" --worker "$_worker_name" --verdict "BLOCKED" --caveats "Max attempts ($MAX_ATTEMPTS) exceeded"
 ```

**Status target mapping:**

| Transition | Target Status |
|---|---|
| `refined_idea_to_planning` | _(no-op — status already set to `planning` at start of design-and-plan.md step 0)_ |
| `planning_to_plan_drafted` | `plan-drafted` |

Update status (skip for `refined_idea_to_planning` — already set):
```text
if [ "$_transition" != "refined_idea_to_planning" ]; then
 invoke the Yoke advance skill for YOK-${_num} with target {target}
fi
```

**Epic task status sync:** When `planning_to_plan_drafted` succeeds, cascade task statuses through the centralized owner:
```bash
if [ "$_transition" = "planning_to_plan_drafted" ]; then
 # Read the task list once, then for each row still at planning:
 yoke epic-tasks list --epic "$_num"
 yoke workflow-item epic-task update-status --epic "$_num" --task-num "{task_num}" --status plan-drafted
fi
```

---

## 5l. Post-Verdict Deployment Flow Extraction (refined_idea_to_planning only)

After a successful `refined_idea_to_planning` verdict (READY or CAVEATS) and status update, extract the deployment flow from the spec and write it to the `deployment_flow` column.

This step fires **only** when:
- `_transition` is `refined_idea_to_planning`
- `_verdict` is `READY` or `CAVEATS`

If either condition is not met, skip this step entirely.

```bash
if [ "$_transition" = "refined_idea_to_planning" ] && { [ "$_verdict" = "READY" ] || [ "$_verdict" = "CAVEATS" ]; }; then
 # Read spec silently
 _dod_spec=$(yoke items get $_num spec 2>/dev/null)
 # Fallback to body for non-migrated items
 if [ -z "$_dod_spec" ]; then
 _dod_spec=$(yoke items get $_num body 2>/dev/null)
 fi
 # FR-5: Re-read guard — if empty, retry once after 1s (defense-in-depth layer 3)
 if [ -z "$_dod_spec" ]; then
 echo "WARNING: spec read returned empty for YOK-$_num in deployment flow extraction — retrying after 1s" >&2
 sleep 1
 _dod_spec=$(yoke items get $_num spec 2>/dev/null)
 if [ -z "$_dod_spec" ]; then
 _dod_spec=$(yoke items get $_num body 2>/dev/null)
 fi
 if [ -n "$_dod_spec" ]; then
 echo "RECOVERED: spec re-read succeeded for YOK-$_num in deployment flow extraction" >&2
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
 yoke items scalar update "YOK-$_num" --field deployment_flow --value "$_extracted_flow"
 echo "Deployment flow set: $_extracted_flow for YOK-$_num"
 else
 echo "WARNING: Extracted flow ID '$_extracted_flow' not found in deployment_flows table. Skipping deployment_flow update."
 fi
 else
 echo "NOTE: No deployment flow found in Definition of Done section for YOK-$_num. Skipping deployment_flow update."
 fi
fi
```

**Graceful degradation:** If the `## Definition of Done` section is missing, or the `Flow:` field is absent, or the flow ID does not match any known flow, the extraction silently skips. No error is raised -- the deployment flow can be set manually later.

---

## 5m. Post-Verdict QA Requirement Seeding (refined_idea_to_planning only)

After a successful `refined_idea_to_planning` verdict (READY or CAVEATS) and status update, seed initial `qa_requirements` rows for the item. This ensures every epic has explicit QA requirements before implementation begins.

This step fires **only** when:
- `_transition` is `refined_idea_to_planning`
- `_verdict` is `READY` or `CAVEATS`

If either condition is not met, skip this step entirely.

```bash
if [ "$_transition" = "refined_idea_to_planning" ] && { [ "$_verdict" = "READY" ] || [ "$_verdict" = "CAVEATS" ]; }; then
 # 1. Read ACs from spec (silently pattern)
 _qa_seed_spec=$(yoke items get $_num spec 2>/dev/null)
 if [ -z "$_qa_seed_spec" ]; then
 _qa_seed_spec=$(yoke items get $_num body 2>/dev/null)
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
 --item "YOK-$_num" \
 --qa-kind "ac_verification" \
 --qa-phase "verification" \
 --blocking-mode "blocking" \
 --requirement-source "ac_derived" \
 --success-policy "$_ac_desc" >/dev/null 2>&1 || true
 _qa_ac_count=$((_qa_ac_count + 1))
 ;;
 esac
 done

 # 4. Seed browser requirements from the structured browser_qa_metadata.
 # The Python helper reads the validated metadata (negative default when
 # unset), builds one browser_smoke per route and per AC-derived timing
 # hint, optionally adds a browser_diff per route when visual_outcome is
 # set, and returns a batch payload. Non-browser items produce an empty
 # list and the insert step is skipped.
 _qa_base_url="http://localhost:3000"
 _qa_project=$(yoke items get $_num project 2>/dev/null) || true
 if [ -n "$_qa_project" ] && [ "$_qa_project" != "null" ]; then
 _qa_cap_settings=$(yoke projects capability-settings get --project "$_qa_project" --cap-type browser-qa 2>/dev/null) || true
 _qa_cap_url=$(python3 -c 'import json,sys; print((json.load(sys.stdin) or {}).get("base_url", ""))' <<<"$_qa_cap_settings" 2>/dev/null) || true
 if [ -n "$_qa_cap_url" ]; then _qa_base_url="$_qa_cap_url"; fi
 fi

 _qa_batch_payload=$(python3 -c "
import json
from yoke_core.domain.qa_requirements import build_browser_requirements_from_metadata
rows = build_browser_requirements_from_metadata(
 $_num,
 '$_qa_base_url',
 include_diff=True,
)
print(json.dumps(rows))
") || _qa_batch_payload="[]"

 if [ -n "$_qa_batch_payload" ] && [ "$_qa_batch_payload" != "[]" ]; then
 printf '%s' "$_qa_batch_payload" | yoke qa requirement add-batch --item "YOK-$_num" --stdin >/dev/null 2>&1 || true
 echo "QA: Seeded browser requirements from metadata for YOK-$_num"
 fi

 # 5. If no ACs found, seed at least one implementation review requirement
 _qa_existing_count=$(yoke db read --format lines "SELECT COUNT(*) FROM qa_requirements WHERE item_id=$_num" 2>/dev/null) || true
 if [ -z "$_qa_existing_count" ] || [ "$_qa_existing_count" = "0" ]; then
 yoke qa requirement add \
 --item "YOK-$_num" \
 --qa-kind "implementation_review" \
 --qa-phase "verification" \
 --blocking-mode "blocking" \
 --requirement-source "seeded_default" \
 --success-policy "Implementation matches the item spec" >/dev/null 2>&1 || true
 fi

 echo "QA: Seeded requirements for YOK-$_num at refined_idea_to_planning"
 unset _qa_seed_spec _qa_seed_acs _qa_batch_payload
fi
```

**Behavior notes:**
- Seeding is idempotent per-requirement-source: duplicate calls create additional rows (harmless since each run is tracked independently). The `requirement_source=ac_derived` and `requirement_source=seeded_default` values distinguish shepherd-seeded requirements from manually-added ones.
- If the item has no ACs (title-only), a single `implementation_review` requirement is seeded as a fallback.
- Browser QA seeding reads the validated `browser_qa_metadata` structured field and delegates scenario construction to `build_browser_requirements_from_metadata`. Non-browser items hold the explicit negative default, so the helper returns zero rows and the batch insert is skipped quietly.
- Errors during seeding are swallowed (`|| true`) — QA seeding should never block the shepherd pipeline.
