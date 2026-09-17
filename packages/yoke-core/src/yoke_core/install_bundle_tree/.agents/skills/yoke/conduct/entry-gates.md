# /yoke conduct — arguments, file-scope posture, and pre-dispatch gates

Read this once, before routing. It is the entry contract: what the
invocation may carry, which file-scope axes are effective, and the three
hard blocks that must pass before any dispatch.

## Arguments

Required:

- `PREFIX-N`: The backlog item to conduct. Run one item through the Engineer/Tester loop.

Optional flags:

- `--max-attempts N` (optional): override default retry limit. Default is **5**.
- `--no-chain` (optional, epic only): stop after the current epic task. Do not auto-dispatch the next task in the worktree chain.
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

1. **Dispatch gate (HARD BLOCK):** Read item status:
 ```bash
 _gate_status=$(yoke items get PREFIX-N status)
 ```
 - If `_gate_status` is `planned`, `implementing`, or `reviewing-implementation`: proceed.
 - Otherwise: hard-block with status-appropriate remediation:
 > GATE [hard-block]: Item not at a dispatchable status.
 > PREFIX-N is at status '{_gate_status}', not 'planned', 'implementing', or 'reviewing-implementation'.
 - `idea`, `refining-idea`: > Remediation: Run `/yoke refine PREFIX-N` to refine the spec.
 - `refined-idea`, `planning`: > Remediation: Run `/yoke shepherd PREFIX-N` to drive planning through `plan-drafted`.
 - `plan-drafted`, `refining-plan`: > Remediation: Run `/yoke refine PREFIX-N` to refine the plan to `planned`.
 - After `reviewing-implementation` (`reviewed-implementation`, `polishing-implementation`): > Remediation: Run `/yoke polish PREFIX-N` to finish implementation polish.
 - `implemented` or `release`: > Remediation: Run `/yoke usher PREFIX-N` to merge and deploy.
 - `done`: > Item is already done. No conduct needed.
 - Exceptional (`blocked`, `stopped`, `failed`, `cancelled`): > Item is in an exceptional state. Resolve the block or use an explicit operator-debug repair path before retrying.

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
 > Remediation: Run '/yoke shepherd PREFIX-N' to add acceptance criteria.

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
