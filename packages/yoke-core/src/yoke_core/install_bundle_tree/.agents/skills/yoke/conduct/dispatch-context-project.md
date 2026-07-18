# 5f-project. Project Context Injection (shared sub-step)

Extracted from `dispatch-context.md`. Referenced from `5f-issue.2` (Build Context Block) and `5f-epic.6` (Build Context Block).

This sub-step is called as the **final sub-step** of both `5f-issue.2` (Build Context Block) and `5f-epic.6` (Build Context Block). It appends project-specific context to the existing context block for items belonging to non-yoke projects. The same context fields (test commands, repo path, ephemeral URL) are documented in `shared/tester-dispatch-template.md` for use by non-conduct flows.

**1. Query the item's project:**
```bash
_project=$(yoke items get "${_id}" project)
```

**2. Skip for yoke items:** If `_project` is empty or `'yoke'`, skip this sub-step entirely. No project context is needed for Yoke's own items.

**3. For non-yoke projects, assemble the project context block:**

a. Read the project-wide always-included docs from the `context_routing` Project Structure family. The reserved `entry_key="always"` holds the list (one path per line; exit 1 with no output when no entry exists):
```bash
_always_docs=$(python3 -m yoke_core.domain.context_routing get-always "${_project}" 2>/dev/null) || true
```

b. List configured topics in the same family. Each non-`always` `entry_key` is a topic name:
```bash
_topics=$(python3 -m yoke_core.domain.context_routing list-topics "${_project}")
```

Match the item title keywords against topic names using this hardcoded heuristic:
- Keywords `frontend`, `dashboard`, `UI` (case-insensitive) -> `frontend` topic
- Keywords `backend`, `api`, `server` (case-insensitive) -> `backend` topic
- Keywords `test`, `testing` (case-insensitive) -> `testing` topic
- Keywords `deploy`, `deployment` (case-insensitive) -> `deployment` topic

For each matched topic that appears in `$_topics`, fetch its docs (one path per line):
```bash
_topic_docs=$(python3 -m yoke_core.domain.context_routing get-topic "${_project}" "${_topic}" 2>/dev/null) || true
```

c. Read `repo_path`:
```bash
_repo_path=$(yoke projects get --project "${_project}" --field repo_path)
```

d. Read test commands (four-tier model). Project-level test commands live in the `command_definitions` Project Structure family:
```bash
_cmd_quick=$(python3 -m yoke_core.domain.command_definitions get "${_project}" quick)
_cmd_full=$(python3 -m yoke_core.domain.command_definitions get "${_project}" full)
_cmd_e2e=$(python3 -m yoke_core.domain.command_definitions get "${_project}" e2e)
_cmd_smoke=$(python3 -m yoke_core.domain.command_definitions get "${_project}" smoke)
```

d1. Validate test commands — detect broken commands before agents try to use them. The Python owner is `yoke_core.domain.projects validate-test-commands`; it prints `project=<id>` followed by one line per canonical scope in the form `<scope>=<valid|invalid|empty>|<detail>` and exits 0 when nothing is invalid. An empty value is reported as `empty`, not `invalid`:
```bash
_validation_output=$(python3 -m yoke_core.domain.projects validate-test-commands "${_project}" 2>/dev/null) || true
_quick_status=$(printf '%s' "$_validation_output" | grep '^quick=' | sed 's/^[^=]*=//; s/|.*//')
_full_status=$(printf '%s' "$_validation_output" | grep '^full=' | sed 's/^[^=]*=//; s/|.*//')
_e2e_status=$(printf '%s' "$_validation_output" | grep '^e2e=' | sed 's/^[^=]*=//; s/|.*//')
_smoke_status=$(printf '%s' "$_validation_output" | grep '^smoke=' | sed 's/^[^=]*=//; s/|.*//')
if [ "$_quick_status" = "invalid" ]; then _cmd_quick=""; fi
if [ "$_full_status" = "invalid" ]; then _cmd_full=""; fi
if [ "$_e2e_status" = "invalid" ]; then _cmd_e2e=""; fi
if [ "$_smoke_status" = "invalid" ]; then _cmd_smoke=""; fi
```

If any status is "invalid", emit a warning and downgrade that command to empty in the dispatch context. Do not inject broken commands into agent prompts — they waste agent time debugging missing scripts. The warning identifies the exact project and scope for repair.

d2. Query ephemeral environment URL:
```bash
# Branch naming contract: branch MUST be 'YOK-{id}' — see db-reference.md § ephemeral_environments
_ephemeral_url=$(yoke db read --format lines "SELECT url FROM ephemeral_environments WHERE project_id=(SELECT id FROM projects WHERE slug='${_project}') AND branch='YOK-${_id}' AND status='healthy' LIMIT 1")
```
If the query returns empty, set `_ephemeral_url` to `"none"`. This gracefully handles the case where no ephemeral environment exists for the item's branch.

e. For each file path in `_always_docs` + matched topic docs, read the file contents from `{_repo_path}/{file_path}`. If a file does not exist, log a warning and skip it (do NOT error out):
```
Warning: project context file not found: {_repo_path}/{file_path} — skipping
```

f. Append the project context block to the existing context block:
```
## Project Context: {_project}
Repo: {_repo_path}
Worktree: {_worktree_path}
Yoke DB: {YOKE_DB}
Ephemeral URL: {_ephemeral_url}
IMPORTANT: Do NOT modify Yoke's own scripts. Work only within the project repo.

### {filename}
{file contents}
```

One `### {filename}` / `{file contents}` section per successfully-read context file.

After `5f-project` completes, run **5f-project-ephemeral** in [dispatch-context-gates.md](dispatch-context-gates.md) for non-yoke projects.
