# Shared Tester Dispatch Template

Referenced by:
- `conduct/dispatch-context.md` (issue item prompt template, epic task prompt template)
- `advance/implementing/SKILL.md` (ad-hoc Tester dispatch outside conduct)

This file defines the **minimum structured context** that any Tester dispatch MUST include. Without this context, the Tester agent improvises its validation approach — guessing test commands, missing changed files, and producing suboptimal results (see).

---

## When to dispatch a Tester

A Tester dispatch is appropriate when:
1. The item has `qa_requirements` rows that need agent verification (not browser-substrate)
2. The item needs deliberate agent verification before a `reviewed-implementation` or `done` transition outside the conduct pipeline
3. The operator explicitly requests Tester validation

**Browser QA requirements** (`browser_smoke`, `browser_diff`) are handled automatically by the `yoke qa browser run` orchestrator in the advance browser-QA gate (`advance/browser-qa.md`). Do NOT dispatch a Tester agent for browser-kind requirements.

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

### 2. Project Test Commands

**Always include this block** — even for `yoke` project items. For
`yoke` items, the commands may be empty, but including the block
prevents the Tester from guessing.

Read the item's project via the `items.get.run` function call
(envelope in
[`../idea/body-and-sync-functions.md`](../idea/body-and-sync-functions.md))
with `target = {kind: "item", item_id: <N>}` and `payload = {fields:
["project"]}`. The response carries `result.fields.project`.

Project-level test commands live in the `command_definitions` Project
Structure family. Read each scope through the
`yoke_core.domain.command_definitions` Python module, which is the
authoritative read for the family. The structured function-call
dispatch surface for command-definitions reads
(`project_structure.command_definitions.get`) is a follow-up; for now
the module CLI is the explicit retained-boundary read for project
test commands:

```bash
# Retained-boundary: command_definitions module read.
# {_item_project} comes from the items.get.run response above.
_cmd_quick=""
_cmd_full=""
_cmd_e2e=""
_cmd_smoke=""
if [ -n "$_item_project" ] && [ "$_item_project" != "null" ]; then
 _cmd_quick=$(python3 -m yoke_core.domain.command_definitions get "$_item_project" quick 2>/dev/null) || true
 _cmd_full=$(python3 -m yoke_core.domain.command_definitions get "$_item_project" full 2>/dev/null) || true
 _cmd_e2e=$(python3 -m yoke_core.domain.command_definitions get "$_item_project" e2e 2>/dev/null) || true
 _cmd_smoke=$(python3 -m yoke_core.domain.command_definitions get "$_item_project" smoke 2>/dev/null) || true
fi
```

**Four-tier test model:** `quick` = fast signal, `full` = everything including browser integration tests, `e2e` = real end-to-end against a deployed backend, `smoke` = shallow real-stack checks. An absent `e2e` scope means the project has no real E2E suite — not that browser integration tests go there.

**Validate configured commands before dispatching.** Run `yoke_core.domain.projects validate-test-commands` to detect broken commands before handing them to the Tester as authoritative. The validator emits one line per scope in the form `<scope>=<status>|<detail>` (`quick`, `full`, `e2e`, `smoke`). Invalid scopes should be downgraded to "none configured" in the dispatch prompt so the Tester does not waste time running missing scripts; the warning itself goes to the dispatch log so the operator can repair the project config:

```bash
if [ -n "$_item_project" ] && [ "$_item_project" != "null" ]; then
 _validation_output=$(python3 -m yoke_core.domain.projects validate-test-commands "$_item_project" 2>/dev/null) || true
 _quick_status=$(printf '%s' "$_validation_output" | grep '^quick=' | sed 's/^[^=]*=//; s/|.*//')
 _full_status=$(printf '%s' "$_validation_output" | grep '^full=' | sed 's/^[^=]*=//; s/|.*//')
 _e2e_status=$(printf '%s' "$_validation_output" | grep '^e2e=' | sed 's/^[^=]*=//; s/|.*//')
 _smoke_status=$(printf '%s' "$_validation_output" | grep '^smoke=' | sed 's/^[^=]*=//; s/|.*//')
 if [ "$_quick_status" = "invalid" ]; then _cmd_quick=""; fi
 if [ "$_full_status" = "invalid" ]; then _cmd_full=""; fi
 if [ "$_e2e_status" = "invalid" ]; then _cmd_e2e=""; fi
 if [ "$_smoke_status" = "invalid" ]; then _cmd_smoke=""; fi
fi
```

Present each command to the Tester with an inline `⚠️ INVALID` marker when the corresponding status is `invalid`, and prefer "none configured" over shipping a broken command:

```
Project Test Commands:
 Quick: {_cmd_quick or "none configured"} {if _quick_status is "invalid": "⚠️ INVALID — script/executable not found, treating as unconfigured"}
 Full: {_cmd_full or "none configured"} {if _full_status is "invalid": "⚠️ INVALID — script/executable not found, treating as unconfigured"}
 E2E: {_cmd_e2e or "none configured"} {if _e2e_status is "invalid": "⚠️ INVALID — script/executable not found, treating as unconfigured"}
 Smoke: {_cmd_smoke or "none configured"} {if _smoke_status is "invalid": "⚠️ INVALID — script/executable not found, treating as unconfigured"}
```

### 3. Changed files and diff

Read the item's worktree branch via the `items.get.run` function call
(`payload = {fields: ["worktree"]}`). The response carries
`result.fields.worktree`. Then collect the changed files and diff
summary via `git` — `git` is a retained-boundary external command
and stays on the shell surface:

```bash
# {_wt_branch} comes from the items.get.run response above.
# Convention: Tester dispatch is for issue items. For epic tasks,
# conduct dispatches a Tester per task with the task's own worktree
# branch — not this template's {N}.
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
reuse the `_item_project` shell variable from step 2). For
non-yoke projects, read the project's repo path from the wrapped
`projects.get` adapter:

```bash
# {_item_project} comes from items.get.run above.
if [ -n "$_item_project" ] && [ "$_item_project" != "null" ] && [ "$_item_project" != "yoke" ]; then
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

### 5. Ephemeral URL (non-yoke projects)

Read the latest ephemeral environment row for the item's project +
branch via the `ephemeral_env` module CLI (the
`yoke_core.domain.ephemeral_env` Python entrypoint is the
authoritative read for `ephemeral_environments` rows; the
function-call dispatch surface is a follow-up). The query is
read-only and stays on the operator-debug shell surface as a
retained boundary:

```bash
# Retained-boundary: ephemeral_environments URL read.
_ephemeral_url="none"
if [ -n "$_item_project" ] && [ "$_item_project" != "null" ] && [ "$_item_project" != "yoke" ]; then
 _eph=$(python3 -m yoke_core.domain.ephemeral_env get "$_item_project" "YOK-{N}" 2>/dev/null \
   | python3 -c "import json,sys; row=json.loads(sys.stdin.read() or '{}'); print(row.get('url') or '')")
 if [ -n "$_eph" ]; then _ephemeral_url="$_eph"; fi
fi
```

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

 Project Test Commands:
 Quick: {_cmd_quick or "none configured"}
 Full: {_cmd_full or "none configured"}
 E2E: {_cmd_e2e or "none configured"}
 Smoke: {_cmd_smoke or "none configured"}
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
 Run tests using the Project Test Commands above (prefer Quick for fast feedback, Full for thorough validation).
 Return a verdict line:
 VERDICT: PASS or VERDICT: FAIL followed by details.

 OUTPUT DISCIPLINE: End with VERDICT line and a brief summary. Do not echo the full spec or diff back.
```

---

## Conduct vs. advance usage

**Conduct** (`dispatch-context.md`): Populates this context as part of its structured `5f-project` sub-step and the issue/epic Tester prompt templates. The context is built during the conduct batch preparation phase with additional retry-specific fields (per-attempt diffs, dispatch chain tracking).

**Advance** (`advance/implementing/SKILL.md`): References this template when the implementing agent needs to dispatch a Tester for ad-hoc validation outside the conduct pipeline. The advance flow builds the context inline using the same DB queries documented above.
