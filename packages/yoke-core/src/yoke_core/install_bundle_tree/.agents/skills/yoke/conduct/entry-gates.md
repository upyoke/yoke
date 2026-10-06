# /yoke conduct — arguments, file-scope posture, and pre-dispatch gates

Read this once, before routing. It is the entry contract: what the
invocation may carry, which file-scope axes are effective, and the three
hard blocks that must pass before any dispatch.

## Arguments

Required:

- `PREFIX-N`: The backlog item to conduct. Run one item through the Engineer/Tester loop.

Optional flags:

- `--max-attempts N` (optional): override default retry limit. Default is **5**.
- `--no-chain` (optional, generated tasks only): stop after the current epic task. Do not auto-dispatch the next task in the worktree chain.
- `--force` (optional): override simulation gap gate — proceed with dispatch even if CRITICAL gaps exist. Synonym for `--ignore-gaps`.
- `--ignore-gaps` (optional): synonym for `--force`. Either flag enables the override.
- `--no-auto-fix` (optional): skip the automatic fix loop on simulation gaps. When simulation finds gaps, HALT immediately (legacy behavior). Default: auto-fix is ON.

**Argument validation:**

If `PREFIX-N` is not provided, stop with:

> Missing required argument. Usage: `/yoke conduct PREFIX-N`

## Effective File-Scope Posture

Before requiring task budgets, activating claims, or pairing either surface,
call registered `workflows.item.get` through
`yoke workflows item get ITEM --json`. Consume
`result.effective_policies.file_budget` and
`result.effective_policies.path_claims` directly:

- `required_per_task` applies at generated-task scope;
- `required` applies at item scope;
- `optional` is off.

Do not reconstruct either axis from raw policies or posture. The central
projection owns historical schema compatibility and allowed posture
tightening.

Only when both effective axes are enabled may Conduct compare or pair task
File Budgets with claims. With budget off and claims on, claim paths come from
the task execution document/spec and dispatch survey. With budget on and
claims off, task budgets provide sizing and conflict evidence without claim
activation. With both off, Conduct requires neither artifact. The 350-line
authored-file check and Engineer receipt remain universal in all postures.

## Pre-Dispatch Gates

Before routing, enforce the dispatch gate and acceptance criteria gate. Obey
the `# Workflow Execution Instructions` operator block at the top of fetched
item content; it layers on top of, and never replaces, the item's own spec.

1. **Workflow binding and dispatch gate (HARD BLOCK):** Read the live
   workflow projection, then its exact pinned definition:

   ```text
   yoke workflows item get PREFIX-N --json
   yoke workflows version get WORKFLOW VERSION --json
   ```

   Take `WORKFLOW`, `VERSION`, and the current stage from the first read's
   `result.workflow_id`, `result.workflow_version`, and `result.status`.
   In the second read's `result.definition`, compare positions in the ordered
   `stages` array, never stage-id strings. Select the `skill_bindings` row
   satisfying `from_stage_id <= current_stage < through_stage_id` in that
   order. Retain it as `CONDUCT_BINDING`, along with the definition and live
   stage. Entry at `from_stage_id` and re-entry anywhere inside the segment
   proceed only when the selected row's `skill_id` is `conduct`.

   - Check terminal stages before selecting a binding: a terminal item
     stops; no Conduct needed.
   - An unreadable item or pinned definition, an unknown stage/boundary, or
     a missing/ambiguous binding hard-blocks as `conduct_binding_unavailable`.
     Name the item, pinned version, and missing fact; recover by correcting
     the pinned definition through registered workflow surfaces, then reread.
   - A live stage bound to another skill hard-blocks as
     `conduct_skill_not_bound`. Name the current stage, selected skill id,
     and its segment. Recovery: use the entrypoint rendered from that binding;
     do not substitute a remembered workflow-specific command.
   - At `CONDUCT_BINDING.through_stage_id`, Conduct's segment is finished.
     Reread the live binding for the handoff and stop; do not dispatch or
     carry this segment's claim into the next skill.

   Worktree and generated-task shape come from the pinned
   `policies.worktrees` and `policies.generated_children`, never a
   `workflow_id` comparison. Target-stage gates and transitions likewise
   come from this definition. Recheck the live binding before activation if
   the stage changed since this read.

2. **Acceptance criteria gate (HARD BLOCK):** Read item spec (structured field first, body fallback):
 ```bash
 _gate_body=$(yoke items get PREFIX-N spec 2>/dev/null)
 if [ -z "$_gate_body" ]; then
 _gate_body=$(yoke items get PREFIX-N body)
 fi
 ```
 - Search for AC patterns: lines matching canonical `- [ ] AC-` rows or unlabeled `- [ ] ` checkboxes under a `## Acceptance Criteria` section header.
 - If no ACs found: hard-block with:
 > GATE [hard-block]: Missing acceptance criteria.
 > PREFIX-N has no acceptance criteria. Conduct requires ACs to verify.
 > Remediation: Read `yoke items detail get PREFIX-N --json` and resolve the
 > pinned authoring binding. Restore acceptance criteria through that segment
 > before dispatching; report `acceptance_criteria_missing` while they are absent.

3. **Activation dependency gate (HARD BLOCK):** Use the shared hard-block dependency checker with activation-only semantics. Conduct start gating evaluates only `activation` blockers — `integration` and `closure` edges are enforced downstream by merge/usher gates, not at dispatch time:
 ```bash
 _dep_output_file=$(mktemp "${TMPDIR:-/tmp}/conduct-hard-blocks.XXXXXX")
 if python3 -m yoke_core.domain.check_hard_blocks "PREFIX-N" --gate-point activation >"$_dep_output_file" 2>/dev/null; then
 _dep_exit=0
 else
 _dep_exit=$?
 fi
 _dep_output=$(cat "$_dep_output_file")
 rm -f "$_dep_output_file"
 ```
 - If `_dep_exit` is non-zero, hard-block with:
 > GATE [hard-block]: Unresolved activation dependencies.
 > PREFIX-N has unresolved activation dependencies that must be satisfied before conduct dispatch.
 - For each `BLOCKED|PREFIX-{M}|{status}|{title}` line in `_dep_output`, list:
 > - **PREFIX-{M}** ({title}): status `{status}`
 - Then print the authoritative inspection command:
 > Inspect the full dependency graph (both directions):
 > `yoke items dependency list PREFIX-N`
 - Do NOT proceed to dispatch.
 - If `_dep_exit` is 0, continue.


Next: read [`entry-activation.md`](entry-activation.md) and follow it.
