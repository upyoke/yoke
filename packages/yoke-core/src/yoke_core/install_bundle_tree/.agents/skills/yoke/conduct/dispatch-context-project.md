# 5f-project. Project Context Injection (shared sub-step)

Extracted from `dispatch-context.md`. Referenced from `5f-issue.2` (Build Context Block) and `5f-epic.6` (Build Context Block).

This sub-step is called as the **final sub-step** of both `5f-issue.2` (Build Context Block) and `5f-epic.6` (Build Context Block). It appends project-specific context to the existing context block for every item with a project, including Yoke itself. The same context fields (test plans, repo path, ephemeral URL) are documented in `shared/tester-dispatch-template.md` for use by non-conduct flows.

**1. Query the item's project:**
```bash
_project=$(yoke items get "${_id}" project)
```

**2. Skip only projectless items:** If `_project` is empty or `null`, skip this sub-step. A Yoke item follows the same project lookup as any other project.

**3. Assemble the project context block:**

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

d. Read attached test plans and materialized case snapshots:
```bash
_qa_plans=$(yoke qa plan list --project "${_project}" --json)
_qa_requirements=$(yoke qa requirement list --item "${_id}" --json)
```

d1. Include plan names, transition attachments, and every materialized row's
case key, method, instructions, expected outcome, and requirement id in the
dispatch context. The Engineer or Tester executes a runnable row only through:

```bash
yoke qa case run --requirement-id <qa_requirements.id>
```

Plan authoring validates executor configuration, so dispatch never re-parses or
validates embedded command strings.

d2. Read the environment for the actual worktree branch through `yoke
ephemeral-env get "${_project}" "${_worktree_branch}" --json`. If it is not
found or its status is not healthy, set `_ephemeral_url` to `"none"`. Never
guess a `YOK-N` branch or query the table directly; epic lane branches may have
different names.

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
IMPORTANT: Work only within this project's selected worktree; do not edit a different project checkout.

### {filename}
{file contents}
```

One `### {filename}` / `{file contents}` section per successfully-read context file.

After `5f-project` completes, run **5f-project-ephemeral** for every project that carries the capability.
