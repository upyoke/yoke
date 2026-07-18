# Active — Project Context Preflight

Surfaces project documentation before the text-sensitive test audit and file discovery. Called by the active router as Phase 2.

**Context variables** (from router): `{N}`, `{NNN}`, `{title}`, `{WORKTREE_PATH}`

---

## a. Query project context metadata

This phase is the issue implementation entry path's own context loader. It does not depend on the conduct path.

```bash
_item_project=$(yoke items get {N} project 2>/dev/null)
```

If `_item_project` is empty, `null`, or `yoke` -> skip this phase silently.

```bash
_repo_path=$(yoke projects get --project "$_item_project" --field repo_path 2>/dev/null)
# Source-dev/admin reads: populate _always_docs and _context_topics from the
# context_routing Project Structure family. No registered product CLI wrapper
# exists yet.
```

`get-always` prints one path per line and exits 1 with no output when no project-wide entry is configured. `list-topics` prints one topic name per line and always exits 0.

If both `_always_docs` and `_context_topics` are empty -> skip with advisory:
> **Advisory:** Project '{_item_project}' has no `context_routing` entries configured. Proceeding with targeted test audit and file discovery.

If `_repo_path` is empty or not a readable project checkout -> emit a warning and continue without project docs:
> Warning: project repo_path unavailable for '{_item_project}': {_repo_path}. Proceeding without project context docs.

## b. Read always-included docs

`_always_docs` is a newline-separated list of file paths. For each path, read `{_repo_path}/{path}` using the Read tool. If a file does not exist, emit a warning and continue:
> Warning: project context file not found: {_repo_path}/{path} — skipping

## c. Infer relevant topics from title, spec, and acceptance criteria

Read the item's title plus its spec/body, paying attention to the acceptance-criteria checkbox lines as part of the inference corpus.

Match topics in two passes:

1. **Literal topic-name matching first.** For each topic name present in `_context_topics`, check whether that name itself appears in the title/spec/AC text (case-insensitive). This keeps the phase usable for projects with their own topic defaults.
2. **Fallback keyword heuristics second** for the standard shared topics:

| Keywords in title/spec/AC text | Topic |
|---|---|
| `frontend`, `dashboard`, `ui`, `page`, `component`, `css`, `theme`, `layout`, `login`, `form`, `button`, `modal`, `sidebar`, `header`, `footer`, `style`, `responsive`, `animation` | `frontend` |
| `backend`, `api`, `server`, `endpoint`, `route`, `handler`, `middleware`, `database`, `query`, `migration` | `backend` |
| `test`, `testing`, `spec`, `e2e`, `assertion`, `fixture`, `mock` | `testing` |
| `deploy`, `deployment`, `ci`, `cd`, `workflow`, `infra`, `server setup`, `vps`, `nginx`, `docker` | `deployment` |

For each matched topic that appears in `_context_topics`, fetch its docs:
```bash
# Source-dev/admin read: populate _topic_docs for "$_item_project" and "$_topic".
```

**Ambiguity handling:** If multiple topics match, include all of them. If no topics match, emit advisory and continue with the always-included docs plus targeted discovery:
> **Advisory:** No topic match for YOK-{N} in project '{_item_project}' `context_routing` topics. Matched keywords: none. Available topics: {comma-separated topic names}. Proceeding with always-included docs and targeted discovery.

## d. Read matched topic docs

For each file path from the matched topics, read `{_repo_path}/{path}` using the Read tool. Missing files warn and continue (same as section b).

## e. Surface concrete context for later phases

After reading project docs, emit a structured summary block that later phases can use directly:

```
## Project Context Summary ({_item_project})

**Matched topics:** {comma-separated matched topics, or "none (always-included docs only)"}

**Likely implementation files** (extracted from project docs):
- {file paths mentioned in the docs that are relevant to this change}

**Likely test/doc surfaces** (extracted from project docs):
- {test file paths, test directories, helper files, docs, or file-pattern guidance mentioned in the docs}

**Known patterns** (extracted from project docs):
- {implementation patterns, conventions, route/file-structure notes, or workflow guidance from the docs}
```

The summary must contain **concrete paths and patterns** taken from the docs that were actually read, not generic advice. If a doc names the route directory, component tree, test helper, fixture, or workflow file, surface that exact path.

**Use of this summary is mandatory in later phases:**
- `test-and-record.md` should use the likely test/doc surfaces to scope the text-sensitive audit before falling back to the broad minimum grep tree.
- `implementation.md` should use the likely implementation files and known patterns before any open-ended exploration.

Broad Explore-style scans remain a fallback for genuinely novel areas not covered by the project's docs.
