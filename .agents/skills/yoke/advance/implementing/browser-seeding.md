# Active — Browser-Testable QA Seeding

Browser-specific QA requirement seeding. Called from `qa-seeding.md` after AC-derived requirements are seeded. Skip entirely if the item is not browser-testable.

**Context variables** (from router): `{N}`, `{NNN}`, `{title}`, `{WORKTREE_PATH}`

---

Seeded scenarios use the **executor vocabulary** from `docs/browser-scenario-schema.md`: field names `route` (not `url`), `target` (not `selector`), and screenshot steps include `"capture": true`.

The seeding path reads `browser_qa_metadata` directly. There is no regex classifier on the execution path: `/yoke idea` writes a validated metadata object at creation time and `/yoke refine` keeps it honest, so the structured field is the authoritative source for `browser_testable`, `visual_outcome`, `browser_routes`, and `browser_timing_hints_ms`. Non-browser items hold the explicit negative-default object; their metadata read produces an empty scenario list and the seeding step self-exits quietly.

**Multi-route scenario generation:** The metadata carries `browser_routes` as a normalized leading-slash list. The builder emits one `browser_smoke` row per route, plus one additional timed `browser_smoke` row per `browser_timing_hints_ms` entry so multi-capture strategies keep distinct success policies.

**Multi-capture strategy splitting:** When multiple timing hints are present for the same route, each produces its own `browser_smoke` requirement. Visual ACs that explicitly require screenshot evidence are tagged with `[requires_screenshot_evidence]` in `ac_verification` requirements to prevent agent-only pass.

**Pre-screenshot settle-delay floor:** Every seeded `navigate` → `screenshot` sequence ends up with at least a 2000 ms `delay` between them. The floor kills the common race where the first screenshot lands on a spinner, skeleton loader, or un-hydrated font swap instead of the real render. An AC-derived timing hint larger than the floor (e.g., "visible 7 s post-load" → 7000 ms) replaces the floor; it does not stack with it. `build_browser_scenario_policy()` in `yoke_core.domain.qa_requirements` is the single source of truth — smoke, timed, and diff rows all route through it, so no caller needs to re-implement the logic. The sibling `min_delay_before_first_screenshot(timing_hint_ms)` helper exposes the same `max(2000, hint)` math for callers that need the number in isolation.

```bash
# 1. Read the authoritative metadata.
_metadata_json=$(yoke items get YOK-{N} browser_qa_metadata 2>/dev/null) || true
if [ -z "$_metadata_json" ] || [ "$_metadata_json" = "null" ]; then
 # Pre-migration backstop: surface the gap, skip seeding, let the preflight
 # helper catch the drift in aggregate. Do NOT silently fall back to regex parsing.
 echo "Advisory: YOK-{N} has no browser_qa_metadata — skipping browser QA seeding."
else
 _browser_testable=$(printf '%s' "$_metadata_json" | python3 -c "import json, sys; print(json.load(sys.stdin).get('browser_testable', False))")

 if [ "$_browser_testable" = "True" ]; then
 # 2. Dedup guard: shepherd or a prior advance may have already seeded.
 _existing_browser=$(yoke db read --format lines \
 "SELECT COUNT(*) FROM qa_requirements WHERE item_id={N} AND qa_kind IN ('browser_smoke','browser_diff','e2e','visual_regression') AND requirement_source='seeded_default'" 2>/dev/null) || true

 if [ -z "$_existing_browser" ] || [ "$_existing_browser" = "0" ]; then
 # 3. Resolve base_url: prefer ephemeral, fall back to project capability, then localhost.
 _base_url="http://localhost:3000"
 _item_proj=$(yoke items get {N} project 2>/dev/null) || true
 if [ -n "$_item_proj" ] && [ "$_item_proj" != "null" ]; then
 _eph_url=$(yoke db read --format lines "SELECT url FROM ephemeral_environments WHERE project_id=(SELECT id FROM projects WHERE slug='${_item_proj}') AND branch='YOK-{N}' AND url IS NOT NULL AND url <> '' LIMIT 1" 2>/dev/null) || true
 if [ -n "$_eph_url" ]; then
 _base_url="$_eph_url"
 else
 _cap_settings=$(yoke projects capability-settings get --project "$_item_proj" --cap-type browser-qa 2>/dev/null) || true
 _cap_url=$(python3 -c 'import json,sys; print((json.load(sys.stdin) or {}).get("base_url", ""))' <<<"$_cap_settings" 2>/dev/null) || true
 if [ -n "$_cap_url" ]; then _base_url="$_cap_url"; fi
 fi
 fi

 # 4. Only emit browser_diff when a baseline already exists for the first
 # route, so the very first pass does not fail against no comparison source.
 _visual_outcome=$(printf '%s' "$_metadata_json" | python3 -c "import json, sys; print(json.load(sys.stdin).get('visual_outcome', False))")
 _include_diff="False"
 if [ "$_visual_outcome" = "True" ]; then
 _first_route=$(printf '%s' "$_metadata_json" | python3 -c "import json, sys; routes=json.load(sys.stdin).get('browser_routes') or ['/']; print(routes[0])")
 _has_baseline=$(yoke db read --format lines \
 "SELECT COUNT(*) FROM qa_artifacts WHERE artifact_type='screenshot' AND artifact_handle LIKE '%${_item_proj}%' AND artifact_handle LIKE '%${_first_route}%' AND id NOT IN (SELECT id FROM qa_artifacts WHERE artifact_handle LIKE '%YOK-{N}%')" 2>/dev/null) || _has_baseline="0"
 if [ -n "$_has_baseline" ] && [ "$_has_baseline" -gt 0 ] 2>/dev/null; then
 _include_diff="True"
 fi
 fi

 # 5. Build scenario rows from metadata via the Python-owned helper and
 # insert them through the batch surface in one transaction.
 _batch_payload=$(python3 -c "
import json
from yoke_core.domain.qa_requirements import build_browser_requirements_from_metadata
rows = build_browser_requirements_from_metadata(
 {N},
 '${_base_url}',
 include_diff=(${_include_diff}),
)
print(json.dumps(rows))
")

 if [ -n "$_batch_payload" ] && [ "$_batch_payload" != "[]" ]; then
 printf '%s' "$_batch_payload" | yoke qa requirement add-batch --item "YOK-{N}" --stdin
 fi
 fi
 fi
fi
```

The helper returns zero rows when `browser_testable=false` and one row per `(route × (smoke + each timing hint))` pair otherwise, with an optional `browser_diff` per route when `include_diff=True`. Every `success_policy` carries the canonical `type=browser_scenario` shape with the pre-screenshot settle-delay floor injected by `build_browser_scenario_policy`.

**Intentional simplifications versus the prior regex-driven path:** The previous skill extracted selectors, quoted text, and semantic keywords from AC prose to generate smarter assert steps inline. Those heuristics were unreliable — selectors had to exist literally in the spec, quoted text had to be short, and the fallback keyword filter was aggressive. The metadata path trades that speculative step-building for structural honesty: navigate, settle, screenshot, and an optional diff step when visual. When richer assert steps are required, they belong in a refine or polish pass against the already-seeded requirement, not speculated from prose at seeding time.

This step is a no-op if shepherd already seeded browser requirements at `refined_idea_to_planning`; the dedup count check prevents double-seeding.

**Python-owned JSON construction:** When assembling a success_policy outside the batch helper above, use `build_browser_scenario_policy()` so the settle-delay floor is enforced and JSON escaping is safe:

```bash
_smoke_policy=$(python3 -c "
from yoke_core.domain.qa_requirements import build_browser_scenario_policy
import json
steps = ${_steps}
print(build_browser_scenario_policy('${_base_url}', steps))
")
```

Ad-hoc scenario JSON assembly — heredocs, string-concatenation of raw JSON inside shell — broke on double quotes inside `success_policy` values and is no longer used anywhere in this skill.
