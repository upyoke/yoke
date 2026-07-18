# Conduct — Simulation Gate Escalation Paths

Invoked from `simulation-gate-criteria.md` after `_local_result` and `_verified_verdict` are set. Covers CLEAN handoff, GAPS FOUND branch selection, auto-fix invocation, and return handling.

**Inherited:** `MAIN_ROOT`, `_epic_id`, `N`, `_worktree_path`, `_worktree_branch`, `_max_attempts`, `MAX_ARCHITECT_FIX_ITERATIONS`, `_project`, `_local_result`, `_verified_verdict`, `_simulation_gaps` (Simulator output).

---

### Pre-Branch HALT Conditions

Some halt paths fire before the result branching below — they short-circuit straight to `cleanup-report.md` with `HALTED`:

| Source | Condition | Diagnostic |
|---|---|---|
| `simulation-gate-criteria.md` defensive precondition | `_epic_id` is empty or unset before any Simulator dispatch (initial or retry) | `[CRITICAL] _epic_id lost between dispatches — refusing retry. Halting simulator gate.` |
| `simulation-gate-criteria.md` Simulator Output Gate | `_simulator_output_failures` > `MAX_SIMULATOR_REPROMPTS` after the no-tool fallback | `[CRITICAL] Simulator output gate exhausted retries` |
| `persist_simulation` exit 16 | Body's attested epic differs from CLI-passed `_epic_id` | `[CRITICAL] simulator returned body for wrong epic — CLI passed YOK-${_epic_id}, body attested a different epic.` |
| `persist_simulation` exit 17 | Body has no `EPIC: YOK-N` line and no legacy heading fallback | `[CRITICAL] simulator output for YOK-${_epic_id} has no EPIC: YOK-N attestation line.` |

When any of these fire, conduct does NOT enter result branching; it goes straight to `cleanup-report.md` with `HALTED` and surfaces the diagnostic so the operator sees the wrong-epic / missing-epic / lost-context outcome explicitly.

### Result Branching

#### If `_local_result` is `CLEAN`

- **Satisfy parent epic item-level verification requirements.** All epic tasks passed testing and simulation is clean. Record passing QA runs for unsatisfied blocking verification requirements:
 ```bash
 _unsatisfied_reqs=$(yoke db read --format lines "SELECT r.id, r.qa_kind FROM qa_requirements r WHERE r.item_id=${N} AND r.qa_phase='verification' AND r.blocking_mode='blocking' AND r.waived_at IS NULL AND NOT EXISTS (SELECT 1 FROM qa_runs qr WHERE qr.qa_requirement_id=r.id AND qr.verdict='pass')")
 ```
 For each unsatisfied requirement (parse `id|qa_kind` per line):
 - Skip `simulation` kind — already satisfied by the `persist_simulation` call above.
 - Skip `browser_smoke` and `browser_diff` — require `executor_type='browser_substrate'`.
 - Otherwise record a passing run:
 ```bash
 yoke qa run add \
 --requirement-id {_req_id} --executor-type "agent" --qa-kind "{_qa_kind}" \
 --verdict "pass" \
 --raw-result "Satisfied from conduct evidence: all ${_task_count} epic tasks passed + integration simulation CLEAN"
 ```

- **Auto-handoff and claim release.** The `persist_and_verify` call auto-triggered `conduct_reviewed_handoff` on CLEAN verdict (T-1), which released the Conduct item claim with reason `handoff-to-polish` (T-4). Verify:
 ```bash
 _parent_status=$(yoke items get "${N}" status 2>/dev/null)
 ```
 If `_parent_status` is NOT `reviewed-implementation`: **HALT**. Auto-handoff failed. Do NOT write `status reviewed-implementation` manually. **Go to `cleanup-report.md`** with `HALTED`.

- Do NOT run done-transitions, close the GitHub issue, or remove the worktree. Print:
 ```
 All tasks in this worktree complete. Run '/yoke polish YOK-{N}' to finish the parent epic.
 ```
- **Go to `cleanup-report.md`** with `SUCCESS`.

---

#### If `_local_result` is `GAPS FOUND`

Store `_simulation_gaps` with gap details from Simulator output.

Parse severity counts and recommendation:
```bash
_critical_count=$(echo "$_simulation_gaps" | grep -c '\[CRITICAL\]' || true)
_warning_count=$(echo "$_simulation_gaps" | grep -c '\[WARNING\]' || true)
_recommendation=$(echo "$_simulation_gaps" | grep '^- Recommendation:' | sed 's/.*Recommendation: //')
```

##### Branch 1 — PROCEED with no CRITICALs (file tickets, proceed)

**Condition:** `_critical_count = 0` AND `_recommendation = "PROCEED"`.

Print: `Simulation found WARNING/NOTE gaps but Simulator recommends PROCEED. Filing follow-up tickets.`

For each `### GAP #N:` block in `_simulation_gaps`:
1. Extract: title, severity, category, tasks involved, "what happens", root cause, fix guidance.
2. Map priority: `[WARNING]` → `medium`, `[NOTE]` → `low`.
3. Create item (sanctioned direct-add exception):
 ```bash
 _add_output=$(yoke items create "Sim gap: {gap_title}" issue --project "$_project" --priority {priority} --idea-intake)
 _new_id=$(echo "$_add_output" | sed -n 's/.*YOK-\([0-9][0-9]*\).*/\1/p')
 ```
4. Set source to `simulation`, write spec to DB, sync to GitHub.

Collect all filed ticket IDs into `_filed_ticket_ids`.
Satisfy parent epic verification requirements** (same logic as CLEAN path — skip `simulation`, `browser_smoke`, `browser_diff` kinds).
PROCEED triage write + reviewed-implementation handoff:
```bash
_gap_summary=$(echo "$_simulation_gaps" | head -c 500)
yoke conduct epic proceed-triage-handoff --epic "${_epic_id}" \
 --recommendation "$_recommendation" \
 --gap-summary "$_gap_summary" \
 --filed-tickets "$(echo "$_filed_ticket_ids" | tr ' ' ',')"
_proceed_rc=$?
```
If `_proceed_rc` non-zero: **HALT**. Do NOT write status manually. **Go to `cleanup-report.md`** with `HALTED`.
If `_proceed_rc` is 0: verify `_parent_status` is `reviewed-implementation`. If not: **HALT**.

**Go to `cleanup-report.md`** with `SUCCESS`.

##### Branch 2 — Auto-fix disabled

**Condition:** `--no-auto-fix` was passed.

Print halt message. **Go to `cleanup-report.md`** with `HALTED`.

##### Branch 3 — Full autofix (CRITICAL gaps or Recommendation ≠ PROCEED)

Read and follow `.agents/skills/yoke/conduct/simulation-autofix.md`. Pass inherited context:
- `MAIN_ROOT`
- `_epic_id`, `N` (as `_item_id`), `_worktree_path`, `_worktree_branch`
- `_simulator_output` = Simulator's raw output from this step
- `_max_attempts`, `MAX_ARCHITECT_FIX_ITERATIONS`

**If auto-fix returns `AUTOFIX_CLEAN`:**
- **Satisfy parent epic verification requirements** (same logic as CLEAN path).
- **Verify auto-handoff after clean autofix.** The `persist_and_verify` inside autofix auto-triggered `conduct_reviewed_handoff.run()` on the final CLEAN result and released the Conduct item claim. Verify:
 ```bash
 _parent_status=$(yoke items get "${N}" status 2>/dev/null)
 ```
 If `_parent_status` is not `reviewed-implementation`: **HALT**. Do NOT write status manually.
- Print: `All tasks in this worktree complete (gaps auto-resolved). Run '/yoke polish YOK-{N}' to finish the parent epic.`
- **Go to `cleanup-report.md`** with `SUCCESS`.

**If auto-fix returns `AUTOFIX_HALTED`:**
- Print halt message with worktree preserved and `--force` bypass hint.
- **Go to `cleanup-report.md`** with `HALTED`.

---

**Handoff:** After simulation processing, always read `.agents/skills/yoke/conduct/cleanup-report.md` for board rebuild, main-repo cleanup, and final report.
