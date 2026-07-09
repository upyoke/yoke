# Shepherd: Boss Review and Verdict Processing

Covers steps 5e-5j: Boss invocation, verdict parsing chain (5 layers), verdict persistence, reflection capture, caveat resolution gate, and verdict result handling.

**Inherited from router:** `MAX_ATTEMPTS`, `_num`, `_type`, `_title`, `_transition`, `_attempt`, `_session_id`, `_worker_name`, `_worker_output`.

**After this step completes:** Return to the router for step 6 (Shepherd Log update), step 7 (transition continuity), step 8 (commit), step 9 (final report).

Read and follow: `boss-verdict-rubric.md` (steps 5f–5i: verdict parsing chain, persistence, reflections, caveat triage)
Read and follow: `boss-verdict-transitions.md` (steps 5j, 5l, 5m: verdict result routing, deployment flow extraction, QA seeding)

---

## 5e. Invoke Boss

After the worker completes (or directly for `planning_to_plan_drafted`), invoke the Boss:

**Do NOT pass artifact content inline.** The Boss agent reads the authoritative artifact from the DB itself using scope-aware `yoke items get` calls. The shepherd sends only metadata. This prevents stale/summarized content from reaching the quality gate.

**No-agent-error framing for verdicts.** When the Boss returns NOT_READY, the shepherd should interpret the rejection as identifying a systemic gap — not an agent failure. If the PM's spec was rejected, the dispatch context may have been insufficient. If the Architect's plan was rejected, the spec may have been ambiguous. Log the systemic interpretation in the Ouroboros reflection.

Before invocation, compute repeated Boss output failures for this item/transition:

```bash
_boss_unparseable_count=$(python3 -m yoke_core.cli.db_router query "SELECT COUNT(*) FROM shepherd_verdicts WHERE item='YOK-$_num' AND transition='$_transition' AND caveats LIKE '%[UNPARSEABLE_BOSS_OUTPUT]%'")
_boss_model_override=""
if [ "$_boss_unparseable_count" -ge 2 ]; then
 _boss_model_override="opus"
 echo "Escalating Boss to opus after ${_boss_unparseable_count} unparseable outputs for $_transition."
fi
```

Capture the current verdict-row high-water mark before invoking the Boss. Layer 2 may only reuse rows inserted after this point; older rows belong to prior attempts and must not satisfy the current parse.

```bash
_pre_boss_verdict_max_id=$(python3 -m yoke_core.cli.db_router query "SELECT COALESCE(MAX(id), 0) FROM shepherd_verdicts WHERE item='YOK-$_num' AND transition='$_transition' AND worker='$_worker_name'")
```

**Boss invocation:**

**Dispatch:** descriptor `DispatchDescriptor(role="boss", extras=(("model","opus"),) if _boss_model_override else ())` rendered via `yoke_core.domain.dispatch_descriptors.render_for_harness(descriptor, harness_id)`. Result-schema markers: `VERDICT: READY|NOT_READY|CAVEATS`, `---REFLECTION-START---`. The descriptor's `prompt: |` block is filled with:
```
 Review YOK-{N} at the {_transition} gate.
 Title: {_title}
 Type: {_type}
 Scope: {scope}
 Transition: {_transition}
 Worker: {_worker_name}
 Repository root: {MAIN_ROOT}

 Read the authoritative artifact from the DB before evaluating:
 {if scope is "spec" or "prd": "yoke items get YOK-{N} spec\n If empty, fall back to: yoke items get YOK-{N} body"}
 {if scope is "plan": "yoke items get YOK-{N} technical_plan\n yoke items get YOK-{N} worktree_plan\n yoke items get YOK-{N} spec\n yoke items get YOK-{N} design_spec\n If any structured field is empty, fall back to: yoke items get YOK-{N} body"}

 {if _sim_report: "Simulator report:\n{_sim_report}"}

 {if _transition is "refined_idea_to_planning": "DEPLOYMENT FLOW CHECK: Verify the spec includes a ## Definition of Done section with Project, Flow, and Rationale fields identifying a deployment flow. If the section is missing or the flow ID is not recognized, issue CAVEATS (not NOT_READY) noting the missing deployment flow selection. This is advisory, not blocking."}

 {if _transition is "planning_to_plan_drafted": "EVENT COVERAGE CHECK: Review the task list and worktree plan. If this epic adds new user-facing workflows, status transitions, or system operations, verify that corresponding yoke events emit calls are included in the task specs. Flag any gaps as caveats."}

 Mandatory review points for this gate:
 - Check self-consistency across the artifact: requirements, ACs, caveats, and narrative must agree.
 - If the artifact changes state or performs writes, verify it explicitly covers failure/recovery behavior and leaves-behind state.
 - If the artifact replaces, removes, or renames behavior, verify it explicitly covers cleanup/deletion of the old path.
 - For rename/removal or broad blast-radius work, verify discovery-oriented grep/search guidance rather than memory-only file lists.
 - For issue-scoped items, unresolved open questions that could change interfaces, files touched, data model, or operator-visible behavior are NOT_READY.

 Evaluate against the acceptance criteria for this transition.
 If this is an issue and the artifact includes a `## Technical Plan` section, evaluate that plan quality explicitly (approach clarity, edge cases, and test strategy) as part of the verdict.
 Return your verdict as a structured VERDICT block.
 Do NOT persist your verdict to the DB. Return it as text only. The shepherd handles all verdict persistence.
```

Where `scope` maps to:
- `refined_idea_to_planning` -> `scope=plan`
- `planning_to_plan_drafted` -> `scope=plan` (final review of all artifacts)

Store this mapped value in `_scope` for parsing and fallback logic.

---

After the Boss returns, continue with:
- **Step 5f–5i** (verdict parsing, persistence, reflections, caveat triage): Read and follow `boss-verdict-rubric.md`
- **Step 5j, 5l, 5m** (verdict result routing, deployment flow extraction, QA seeding): Read and follow `boss-verdict-transitions.md`
