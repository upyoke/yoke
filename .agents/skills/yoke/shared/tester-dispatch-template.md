# Shared Tester Dispatch Template

Referenced by:
- `conduct/dispatch-context.md` (item-level and generated-task prompt templates)
- `advance/implementing/SKILL.md` (ad-hoc Tester dispatch outside conduct)

This file defines the **minimum structured context** that any Tester dispatch MUST include. Without this context, the Tester agent improvises its validation approach — guessing test commands, missing changed files, and producing suboptimal results (see).

---

## When to dispatch a Tester

A Tester dispatch is appropriate when:
1. The item has `qa_requirements` rows that need agent verification (not browser-substrate)
2. The item needs deliberate agent verification before a `reviewed-implementation` or `done` transition outside the conduct pipeline
3. The operator explicitly requests Tester validation

Browser method cases (`browser-check`, `browser-inspection`) execute through
the shared case runner and the advance Browser gate. Do not dispatch a Tester
for those cases.

---

## Required context block

Every Tester dispatch prompt MUST include the following structured context. Use the bash commands shown to populate each field.

### 1. Item identity and spec

The dispatching skill reads the spec via the `items.get.run` function
call (`target = {kind: "item", item_id: <N>}`, `payload = {fields:
["spec"]}`) and embeds it inline in the Tester prompt:

```
Validate YOK-{N}: {title}

{spec content from items.get.run result.fields.spec}
```

### 2. Project Test Plans

**Always include this block** — even when no plan is attached. It prevents the
Tester from guessing test commands or bypassing the method contracts.

Read the item's project via the `items.get.run` function call
(envelope in
[`../idea/body-and-sync-functions.md`](../idea/body-and-sync-functions.md))
with `target = {kind: "item", item_id: <N>}` and `payload = {fields:
["project"]}`. The response carries `result.fields.project`.

Project verification lives in attached QA plans. List the item's materialized
requirements and include every row with a non-null `plan_id`:

```bash
_item_project=$(yoke items get "YOK-{N}" project)
_qa_requirements=$(yoke qa requirement list --item "YOK-{N}" --json)
```

The snapshot includes the case key, method id, instructions, expected outcome,
method configuration, transition, and host baseline. Do not extract and run a
Command method's shell text yourself. Execute each case through the shared
runner so its method selects the executor, verdict path, and evidence:

```bash
yoke qa case run --requirement-id <qa_requirements.id>
```

### 3. Changed files and diff

Read the item's active implementation branch via the `item_worktrees.get`
function call (`payload = {"lane_role": "implementation"}`). The response
carries `result.worktree.branch`. Then collect the changed files and diff
summary via `git` — `git` is a retained-boundary external command
and stays on the shell surface:

```bash
# {_wt_branch} comes from the item_worktrees.get response above.
# Convention: this item-level branch lookup is for a
# single_implementation_lane policy. For generated tasks, conduct
# dispatches a Tester per task with the task's own worktree branch
# rather than the parent item's primary worktree.
if [ -n "$_wt_branch" ] && [ "$_wt_branch" != "null" ]; then
 _changed_files=$(git diff --name-only main..."$_wt_branch" 2>/dev/null) || true
 _diff_stat=$(git diff --stat main..."$_wt_branch" 2>/dev/null) || true
fi
```

Include in the prompt:
```
Changed files:
{_changed_files}

Diff summary:
{_diff_stat}
```

For the full diff, either inline it (if small) or write to a temp file and reference it:
```
Full diff from main available via:
git diff main...{_wt_branch}
```

### 4. Worktree path

Read the item's project via the `items.get.run` function call (or
reuse the `_item_project` shell variable from step 2). For every
project-owned item, read the project's repo path from the wrapped
`projects.get` adapter:

```bash
# {_item_project} comes from items.get.run above.
if [ -n "$_item_project" ] && [ "$_item_project" != "null" ]; then
 _wt_repo=$(yoke projects get --project "$_item_project" --field repo_path)
else
 _wt_repo="{REPO_ROOT}"
fi
_worktree_path="$_wt_repo/.worktrees/YOK-{N}"
```

Include in the prompt:
```
Worktree: {_worktree_path}
Main repo root: {REPO_ROOT}
```

### 5. Ephemeral URL (capable projects)

Read the environment for the item's project and actual worktree branch through
the registered `yoke ephemeral-env get <project> <branch> --json` wrapper.
Skip only projectless items; Yoke follows the same lookup as every other
project.

Run the wrapper once and set `_ephemeral_url` from
`result.environment.url` only when `result.environment.status` is healthy;
otherwise use `none`.

Include in the prompt:
```
Ephemeral URL: {_ephemeral_url}
```

---

## Complete prompt template

**Dispatch:** descriptor `DispatchDescriptor(role="tester")` rendered via `yoke_core.domain.dispatch_descriptors.render_for_harness(descriptor, harness_id)`. Result-schema markers: `VERDICT: PASS|FAIL`, `---REFLECTION-START---`. The descriptor's `prompt: |` block is filled with:
```
 Validate YOK-{N}: {title}

 Spec (read via items.get.run by the dispatcher; embedded inline):
 {spec_content}

 Project Test Plan Cases:
 {_plan_case_rows or "none attached"}
 Execute each runnable row with:
 yoke qa case run --requirement-id <qa_requirements.id>
 Ephemeral URL: {_ephemeral_url}

 Worktree: {_worktree_path}
 Main repo root: {REPO_ROOT}

 Changed files:
 {_changed_files}

 Diff summary:
 {_diff_stat}

 Full diff from main available via:
 git diff main...YOK-{N}

 Review the implementation against the acceptance criteria in the spec.
 Execute the materialized plan cases above through the shared case runner.
 Return a verdict line:
 VERDICT: PASS or VERDICT: FAIL followed by details.

 OUTPUT DISCIPLINE: End with VERDICT line and a brief summary. Do not echo the full spec or diff back.
```

---

## Conduct vs. advance usage

**Conduct** (`dispatch-context.md`): Populates this context as part of its structured `5f-project` sub-step and the item-level/generated-task Tester prompt templates. The context is built during conduct batch preparation with additional retry-specific fields (per-attempt diffs, dispatch chain tracking).

**Advance** (`advance/implementing/SKILL.md`): References this template when the implementing agent needs to dispatch a Tester for ad-hoc validation outside the conduct pipeline. The advance flow builds the context inline using the same DB queries documented above.
