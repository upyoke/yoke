# Advance — Preflight: Gate Checks

Extracted from `preflight.md`. Covers the individual gate checks run before implementation work begins. Read and follow this file when `preflight.md` directs you here.

**Context variables** (inherited from router): `{N}`, `_type`, `_status`, `_target`, `--force` flag

---

## Hard-Block Dependency Gate (step 4-dep)

Skip if target is `idea`, `refining-idea`, `refined-idea`, `planning`, `refining-plan`, or `planned` (pre-implementation statuses where dependencies are not yet enforced).

Applies to targets: `implementing`, `reviewing-implementation`, `reviewed-implementation`, `polishing-implementation`, `implemented`, `release` — any status that starts or continues implementation/delivery work.

**If `--force`:** Skip with warning:
> **Warning:** Hard-block dependency gate overridden with --force.

Determine the gate point based on target status:
- `implementing`, `reviewing-implementation` → gate_point = `activation`
- `reviewed-implementation`, `polishing-implementation`, `implemented`, `release` → gate_point = `integration`

Use the shared dependency-planning kernel. The current evaluator is an internal
service-client handler with no registered product CLI wrapper; it routes through
the same kernel used by frontier, scheduler, usher/collect, and merge preflight.

```bash
# Internal dependency-gate evaluation: populate _dep_gate_json for YOK-{N}
# and "{gate_point}". Do not teach this service-client handler as product flow.
```

If the service-client handler succeeds and returns JSON, parse `is_blocked` and `unsatisfied_blockers`:
- If `is_blocked` is true, **block**. Format the output for the operator using the structured blocker details from the kernel response.

> **Blocked:** YOK-{N} has unresolved dependencies at the `{gate_point}` gate. All blockers must be satisfied before advancing to `{_target}`.

For each entry in `unsatisfied_blockers`:
> - **{blocking_item}** ({blocking_status}): {rationale}

**Fallback:** If the service-client handler is not available (missing python3, missing script, or non-zero exit with no JSON), fall back to the shell-native checker:
```bash
_dep_output_file=$(mktemp "${TMPDIR:-/tmp}/advance-hard-blocks.XXXXXX")
if python3 -m yoke_core.domain.check_hard_blocks "YOK-{N}" --gate-point "{gate_point}" >"$_dep_output_file" 2>/dev/null; then
 _dep_exit=0
else
 _dep_exit=$?
fi
_dep_output=$(cat "$_dep_output_file")
rm -f "$_dep_output_file"
```

If `_dep_exit` is non-zero (blockers found), **block** with the same format as above, using `BLOCKED|{blocker}|{status}|{title}|{gate_point}|{satisfaction}` lines from `_dep_output`.

Then emit the inspection command:
> Inspect the full dependency graph (both directions):
> `yoke shepherd dependency-list YOK-{N}`

Do NOT update status. Do NOT create worktree. Do NOT run any subsequent gates. **Stop.**

If no blockers (kernel says `is_blocked=false` or check-hard-blocks exits 0), proceed silently.

---

## AC Presence Gate (step 4-ac)

Skip if `_type` is `epic` (epics use shepherd's Gate 0 for AC enforcement).

Skip if target is `idea`, `refining-idea`, `refined-idea`, `planning`, `refining-plan`, or `planned` (pre-implementation statuses where ACs are not yet required).

Applies to targets: `implementing`, `reviewing-implementation`, `reviewed-implementation`, `polishing-implementation`, `implemented`, `release` — any status at or past `implementing`.

**If `--force`:** Skip with warning:
> **Warning:** AC presence gate overridden with --force.

Run the shared AC presence checker (accepts both canonical `- [ ] AC-N:` and unlabeled `- [ ] ` under `## Acceptance Criteria`):
```bash
_ac_output_file=$(mktemp "${TMPDIR:-/tmp}/advance-ac-check.XXXXXX")
_ac_stderr_file=$(mktemp "${TMPDIR:-/tmp}/advance-ac-stderr.XXXXXX")
if python3 -m yoke_core.domain.check_ac_presence "YOK-{N}" >"$_ac_output_file" 2>"$_ac_stderr_file"; then
 _ac_exit=0
else
 _ac_exit=$?
fi
_ac_output=$(cat "$_ac_output_file")
_ac_stderr=$(cat "$_ac_stderr_file")
rm -f "$_ac_output_file" "$_ac_stderr_file"
```

If `_ac_exit` is non-zero (no ACs found), **block**:

> **Blocked:** YOK-{N} has no acceptance criteria.
> No checkbox ACs found in the item spec or body — neither canonical `- [ ] AC-N:` nor unlabeled `- [ ] ` under `## Acceptance Criteria`.
> Conduct requires ACs to verify each item.
>
> **Remediation:** Add a `## Acceptance Criteria` section with `- [ ] AC-{N}: {description}` checkboxes to the item spec, then retry.
> Or run `/yoke shepherd YOK-{N}` to drive the item through the full quality pipeline.

Do NOT update status. Do NOT create worktree. Do NOT run any subsequent gates. **Stop.**

If `_ac_exit` is 0 (ACs present):
- If `_ac_stderr` contains "unlabeled checkbox AC", emit advisory:
 > **Advisory:** YOK-{N} has unlabeled checkbox ACs under `## Acceptance Criteria`. Canonical format is `- [ ] AC-N: {description}`. Consider normalizing via `/yoke shepherd YOK-{N}`; the direct label-normalization helper is source-dev/admin only and has no registered product CLI wrapper.
- Proceed regardless (unlabeled ACs satisfy the gate).

---

## DB Mutation Evidence Preflight (step 4-evidence)

Applies to targets `reviewing-implementation`, `reviewed-implementation`, `polishing-implementation`, `implemented`, and `release` — any status at or past the authoring-gate boundary. Skip if `--force` (emits warning). The full block remains at `check_implementing_to_reviewing_implementation_gate`; this preflight surfaces the remediation earlier so the operator sees the miss before committing worktree changes.

```bash
_evidence_report=$(python3 - <<'PY'
import json, sys
from yoke_core.domain.db_mutation_gate import (
    check_implementing_to_reviewing_implementation_gate as _check,
)
try:
    outcome = _check({N})
except Exception as exc:
    print(json.dumps({"skipped": True, "reason": str(exc)}))
    sys.exit(0)
print(json.dumps({
    "is_blocked": not outcome.passed,
    "errors": list(outcome.errors),
}))
PY
)
```

Parse the JSON. If `is_blocked=true`, **advise** (do not hard-block — the gate itself still enforces at the status mutation; this is the operator-facing preview so they can apply modules before wasting a commit round-trip):

> **Advisory:** YOK-{N}'s DB claim evidence is not yet on the authoritative DB. The advance will be rejected by `check_implementing_to_reviewing_implementation_gate` unless the declared migration modules are applied first.
>
> For each entry in `errors`, the message ends with a `Remediation: ...` fragment. Follow it verbatim. Exception-pathway modules (those calling `record_audit_fingerprint`) require an explicit apply against the active Postgres authority — the worktree's validation surface apply is not sufficient. See `.agents/skills/yoke/advance/implementing/test-and-record.md` section a4.

If the report contains `skipped=true` (helper unavailable, item id not found, etc.), continue silently — the hard gate at status update will still enforce.

## Spec Coverage Gate (step 4-cov)

Skip if `_type` is `epic` (epics use shepherd's path-claim handoff). Skip if target is `idea`, `refining-idea`, `refined-idea`, `planning`, `refining-plan`, or `planned` (claim widening can still happen during refine).

Applies to targets `implementing`, `reviewing-implementation`, `reviewed-implementation`, `polishing-implementation`, `implemented`, and `release` — any status at or past implementation entry. **If `--force`:** skip with warning.

The path-claim-required gate (run by `/yoke refine`) verifies *that* a claim exists; this gate verifies that the claim's declared paths cover everything the spec body's `## File Budget` section promises. The seam exists because deferred-coverage path widening (held until upstream blockers release) is currently authored as prose ("widen claim onto X once YOK-Y releases") with no automated reconciliation. This gate catches the drift at the moment it bites.

```bash
# Internal coverage-gate helper: evaluate path-claim/spec coverage for YOK-{N}.
# No registered product CLI wrapper exists yet.
_cov_exit=$?
```

If `_cov_exit` is non-zero, **block** with the helper's stderr verbatim — it already names the missing paths and prints a ready-to-paste `path-claim-widen` remediation command. Do NOT update status. Do NOT create worktree. **Stop.**

If `_cov_exit` is 0, proceed silently. The gate self-skips when:
- the spec body has no `## File Budget` section,
- the File Budget lists no path-shaped tokens, or
- the item has no non-terminal claim rows (path-claim-required gate handles that case).

**Gate classification: `block-by-design`.** At implementation entry the worktree is about to be created; widening a claim onto additional paths *after* the worktree exists risks mutating coverage while edits are already landing, and refine is no longer reachable to author the claim repair (the item has moved past `refining-idea`). The earlier opportunities to repair are already wired: `/yoke idea` and `/yoke refine` both run `idea_readiness_check` and refine's entry handler auto-widens for pure `FILE_BUDGET_NOT_IN_CLAIM` against the existing non-terminal exclusive claim. The sanctioned remediation when this gate fires is either (a) fix the gap upstream by re-running `/yoke refine` on the item before re-attempting advance, or (b) when the spec is genuinely settled and only the claim is wrong, run `yoke claims path widen --claim-id <id> --add-paths <added> --reason "<why widening>" --item YOK-N` directly before re-running advance — the helper's stderr already prints that command. `--force` does not bypass this gate.

## Epic Advisory (step 5)

If `_type` is `epic` and the target status has a dedicated command (`refined-idea` → shepherd, `planned` → plan, `implementing` → conduct), print:
> Note: Epics normally advance via pipeline commands (`/yoke shepherd`, `/yoke plan`, `/yoke conduct`). Advancing manually.

Proceed anyway — manual override is valid.

## Shepherd Lifecycle Gate (step 5-shep, epics only)

Skip if `_type` is not `epic`. Ensures epics passed the shepherd pipeline.

**Pre-check:** Skip if current status is `implementing` or later. Also skip if current is `idea` and target is `implementing` (deliberate bypass).

**If `--force`:** Skip with warning:
> **Warning:** Shepherd lifecycle gate overridden with --force.

**Required verdicts by target:**

| Target | Required verdict |
|---|---|
| `implementing` or later | `planning_to_plan_drafted` = `READY`, `SKIPPED`, or `CAVEATS` (legacy `planned_to_ready` accepted as pre-2026-04-07 compat) |

**Check:**
```bash
_gate_reason=$(python3 -m yoke_core.domain.shepherd_gate check "YOK-{N}")
_gate_exit=$?
```

`planning_to_plan_drafted` is the terminal verdict shepherd writes before handing off to refine. The helper also accepts the legacy `planned_to_ready` transition for epics that passed the pre-2026-04-07 pipeline; no modern producer writes that name.

If `_gate_exit` is non-zero (no qualifying verdict), **block** with `$_gate_reason` followed by this remediation:
> **Blocked:** YOK-{N} has no qualifying shepherd verdict for the Shepherd Lifecycle Gate.
>
> Inspect the verdict history directly: `python3 -m yoke_core.cli.db_router query "SELECT id, transition, verdict, created_at FROM shepherd_verdicts WHERE item='YOK-{N}' ORDER BY id DESC"`.
>
> If the modern verdict (`planning_to_plan_drafted`) is missing but the epic's status is `plan-drafted` or later, the upstream shepherd run did not emit it — re-run `/yoke shepherd YOK-{N}` only if the epic is still at `refined-idea`, otherwise file a follow-up ticket against the shepherd producer path. Modern shepherd does not re-run against plan-drafted or later statuses.

Do NOT update status.

## Epic Task Existence Gate (step 5-gate, epics targeting `planned` or `implementing`)

Skip if not epic or target is not `planned`/`implementing`. **If `--force`:** skip with warning.

```bash
# Convention: see your `epic_tasks` packet stanza for the epic_id column shape.
# For epic items the epic's own numeric ID IS {N} (mirrors shepherd/plan-handoff.md:23).
# Never YOK-prefix this value.
_epic_id={N}
_task_count=$(python3 -m yoke_core.cli.db_router query "SELECT COUNT(*) FROM epic_tasks WHERE epic_id=${_epic_id}")
```

If `_task_count` is 0, **block**: point to `/yoke plan YOK-{N}`.

## Epic Task Completion Gate (step 5a, epics targeting `implemented` or `release`)

Skip if not epic, or if target is `implementing`, `reviewing-implementation`, `reviewed-implementation`, or `polishing-implementation`. This gate applies only when the entire epic is crossing into `implemented` or `release` — not when a single task lane is advancing through its own review cycle. **If `--force`:** skip with warning.

```bash
# Convention: see your `epic_tasks` packet stanza for the epic_id column shape; bare integer, never YOK-prefixed.
_epic_id={N}
_total=$(python3 -m yoke_core.cli.db_router query "SELECT COUNT(*) FROM epic_tasks WHERE epic_id=${_epic_id}")
_done=$(python3 -m yoke_core.cli.db_router query "SELECT COUNT(*) FROM epic_tasks WHERE epic_id=${_epic_id} AND status IN ('done','reviewed-implementation','implemented','release')")
```

- `_total` = 0 → **block** (no tasks)
- `_total` = `_done` → allow
- Otherwise → **block**, list incomplete tasks

## Deferred Items Gate (step 5a-defer, epics targeting `done`)

Skip if not epic or target is not `done`. **If `--force`:** skip with warning.

**a.** Read deferred items SILENTLY from `item_sections` table:
```bash
_defer_section=$(yoke items section get YOK-{N} --section "Deferred Items" 2>/dev/null)
if [ -z "$_defer_section" ]; then
 _defer_spec=$(yoke items get {N} spec 2>/dev/null)
 _defer_section=$(printf '%s' "$_defer_spec" | sed -n '/^## Deferred Items/,/^## /{ /^## Deferred Items/d; /^## /d; p; }')
 unset _defer_spec
fi
```

**b.** If UNFILED entries found → **block** with remediation to file via `/yoke idea`.

**c.** Scan spec for deferral language outside `## Deferred Items` (patterns: "deferred to follow-up", "out of scope for this epic", etc.). Exclude lines with YOK-N refs, lines in fenced code blocks, lines inside the Deferred Items section.

If untracked deferral language found → **block**.

**d.** If both checks pass, proceed silently. Discard `_defer_section`.

---

After all gate checks pass, return to `preflight.md` to continue with recovery/remediation gates.
