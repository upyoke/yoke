# Active — QA Seeding

Seeds QA requirements before implementation begins. Called by the active router as the QA-seeding phase.

**Context variables** (from router): `{N}`, `{NNN}`, `{title}`, `{WORKTREE_PATH}`

---

## QA Lifecycle for Non-Conduct Items

When advancing a non-epic item to `implementing`, the implementing agent is responsible for the full QA loop: seed -> implement -> test -> record. This ensures the done-gate has data to check.

### a. Seed QA Requirements (before coding)

After reading the item's ACs, seed the AC-derived verification requirement. The verification-entry gate (`implementing → reviewing-implementation`) hard-requires at least one `qa_requirements` row, so every non-epic item needs this before it can advance.

**Primary — auto-create.** Run the registered auto-create surface (function id `qa.requirement.auto_create_for_item`). It creates ONE consolidated `ac_verification` requirement (qa_kind=ac_verification, qa_phase=verification, blocking_mode=blocking, requirement_source=ac_derived) whose `success_policy` lists the pytest target plus every AC. It is idempotent — if an AC-derived `ac_verification` requirement already exists (e.g. seeded by shepherd during `planning_to_plan_drafted`) it returns that row instead of creating a duplicate, so no separate dedup check is needed:

```bash
yoke qa requirement auto-create-for-item --item YOK-{N}
```

Confirmed non-browser issues — where the authoritative `browser_qa_metadata` object records `browser_testable=false` — seed automatically here regardless of how the "## Browser QA Metadata" section prose is worded.

**Fallback — manual seed.** If auto-create reports `not_applicable` (it created nothing — e.g. for an item that is neither a confirmed browser nor a confirmed non-browser case), seed one requirement through the registered `qa.requirement.add` surface — NOT auto-create (which already declined):

```bash
yoke qa requirement add \
  --item YOK-{N} \
  --qa-kind ac_verification \
  --qa-phase verification \
  --blocking-mode blocking \
  --requirement-source ac_derived \
  --success-policy "{brief description of what passing looks like}"
```

The write is item-claim-gated; the advance session already holds the work claim, so it dispatches cleanly. Operator-debug fallback inside a checkout: `python3 -m yoke_core.domain.qa requirement-add --item-id {N} ...` (also the only surface for epic-task / deployment-run-attached requirements).

The `--success-policy` field is a human-readable description of what "pass" means (e.g., "test suite passes with zero failures", "config change verified in output"). If the item has NO acceptance criteria (title-only), seed at minimum one requirement with `--qa-kind implementation_review` and `--success-policy "Implementation matches the item title/description"`.

**Screenshot-evidence tagging:** If an AC explicitly requires screenshot or visual capture evidence (patterns: "screenshot", "capture screenshot", "visual evidence", "screenshot proof") AND the item is browser_testable, append ` [requires_screenshot_evidence]` to the `--success-policy` value. This marker prevents the requirement from being satisfied by `executor_type='agent'` alone — `yoke qa run add` rejects agent runs for requirements with this marker. Example: `--success-policy "Confetti animation visible 12 seconds after load [requires_screenshot_evidence]"`.

### Browser-testable seeding

After seeding AC-derived requirements, check browser-testable classification and seed browser-specific requirements. **Read and follow `implementing/browser-seeding.md`** for the full browser-testable seeding logic.

### Project E2E requirement seeding

After browser-testable seeding, check if the project has an `e2e` command defined in the `command_definitions` family AND an ephemeral-env capability. If both exist, seed an `e2e` QA requirement so the advance-to-implemented gate (`advance/project-e2e.md`) can enforce it.

**Four-tier reminder:** The `e2e` scope means a *real end-to-end* suite that runs against a deployed backend (frontend → backend → database). Browser integration tests with mocked APIs belong under the `full` scope. The shallower `smoke` scope is first-class and surfaced by `test-and-record.md`, but is not auto-seeded as a blocking QA requirement here — smoke runs remain part of the deploy pipeline's smoke stage.

```bash
_item_proj_e2e=$(yoke items get {N} project 2>/dev/null) || true
_has_e2e_cmd=""
_has_eph_cap=""

if [ -n "$_item_proj_e2e" ] && [ "$_item_proj_e2e" != "null" ]; then
 # Source-dev/admin read: populate _e2e_cmd_check from the command_definitions
 # Project Structure family. No registered product CLI wrapper exists yet.
 if [ -n "$_e2e_cmd_check" ]; then
 _has_e2e_cmd="1"
 fi
 # Capability check goes through the typed function `projects.capability.has`.
 # The handler returns `result.has` (boolean) — never wrap a
 # `db_router projects has-capability ... 2>&1; echo` shell choreography.
 # Call shape:
 #   {"function": "projects.capability.has",
 #    "target": {"kind": "project", "project_id": "$_item_proj_e2e"},
 #    "payload": {"capability": "ephemeral-env"}}
 # Set _has_eph_cap="1" when result.has is true.
fi

if [ "$_has_e2e_cmd" = "1" ] && [ "$_has_eph_cap" = "1" ]; then
 _existing_e2e=$(python3 -m yoke_core.cli.db_router query \
 "SELECT COUNT(*) FROM qa_requirements WHERE item_id={N} AND qa_kind='e2e'" 2>/dev/null) || true

 if [ -z "$_existing_e2e" ] || [ "$_existing_e2e" = "0" ]; then
 yoke qa requirement add \
 --item "YOK-{N}" \
 --qa-kind "e2e" \
 --qa-phase "verification" \
 --blocking-mode "blocking" \
 --requirement-source "seeded_default" \
 --success-policy "Project E2E suite passes against ephemeral URL"
 fi
fi
```

**IMPORTANT — e2e requirements:** For `e2e` requirements, do NOT record `executor_type='agent'` runs. The E2E gate in `advance/project-e2e.md` handles execution and recording automatically with `executor_type='ci'`. Agents do not need to manually run or record E2E results.
