# Writing to items, and the generated board

The rules file every session loads carries the short normative form of each rule. This document is the deep home the rules file points at: the same rules with the reasoning, the worked failure modes, the flag matrices, and the edge cases that decide close calls. Read the section you need before the action it governs — nothing here is optional background, it is simply longer than a startup channel can carry.

## Structured item writes

**Agents write through the Yoke function-call surface.** Every item mutation — structured-field replace, additive transforms, section upsert, Progress Log append, epic-task body replace, DB-claim amend — is a typed function call dispatched through the Yoke function-call dispatcher. The CLI commands are **retained operator/debug adapters** that build the matching `FunctionCallRequest` internally; agent/skill/dispatch prose teaches the function id, CLI invocations stay valid as labelled operator/debug examples.

Full envelope shape, claim-verification matrix, and the per-family function id reference (`items.structured_field.*`, `items.section.*`, `items.progress_log.append`, `items.scalar.update`, `lifecycle.transition`, `workflow_item.epic_task.*`, `claims.*`, `db_claim.amend`, `qa.*`, `project_structure.patch.apply`, `board.rebuild`, `agents.render.*`) live in [`.yoke/docs/reference/db-reference/functions.md`](.yoke/docs/reference/db-reference/functions.md); dispatcher events are `YokeFunctionCalled`, `DispatcherIdempotencyReplay`, and `DispatcherDownstreamDegraded`.

- **`items.body` is a virtual rendered field.** Not stored in the DB. Read via `yoke items get PREFIX-N body` (renders on demand from structured fields). Raw body writes are unsupported. All content flows through structured fields.

- **Full-field replace (`items.structured_field.replace`):** writes complete content to `spec`, `design_spec`, `technical_plan`, `worktree_plan`, `shepherd_log`, `shepherd_caveats`, `test_results`, or `deploy_log`. Routes through the structured-write path (preserves empty/shrinkage/freeze guards, reports old/new line counts), and with matching `options` syncs the rendered body to GitHub. CLI adapter: `printf '%s' "$content" | yoke items structured-field replace PREFIX-N --field spec --stdin`.

  ```json
  {"function":"items.structured_field.replace","request_id":"<uuid>","actor":{"session_id":"<harness_sessions.session_id>"},"target":{"kind":"item","item_id":42},"payload":{"field":"spec","content":"# Spec\n\n..."},"options":{"sync_github_body":true}}
  ```

- **Additive transforms (`items.structured_field.append_addendum` / `section_upsert` / `section_append`):** preserve existing content, appending a `## heading`-led block (`append_addendum`, `section_append`) or rewriting one in place (`section_upsert`). The agent path is the function call; the read-transform-in-shell-then-pipe-back pattern is blocked by the structured-field-transform lint (suppression `# lint:no-structured-transform-check` is audit-only — still denies). CLI adapter: `printf '%s' "$content" | yoke items structured-field append-addendum PREFIX-N --field spec --heading "..." --source refine --stdin`.

- **Epic-task content (`workflow_item.epic_task.*`):** body replace, split, reassign, add, remove, metadata update; progress notes via `workflow_item.epic_progress_note.append`. The dispatcher resolves the parent epic from `target.kind="epic_task"` and verifies the session holds the epic's work claim. CLI adapter: `printf '%s' "<task body>" | yoke workflow-item epic-task body-replace --epic 833 --task-num 5 --stdin`.

- **Do not misuse task-graph planning fields.** `shepherd_log`, `shepherd_caveats`, and `worktree_plan` are reserved for items whose pinned workflow policies generate `epic_tasks`. Writing them on a workflow with `generated_children=none` is misuse — readers will treat the content as authoritative planning output. For in-flight execution context on any item, use the **Progress Log** section (next bullet).

## Progress Log

For session-continuity context on an item that future agents need to pick up — what's done so far, decisions made, dead ends explored, where to resume after compaction or session swap — write to a **Progress Log** section on the item (works for every workflow). Agents call `items.progress_log.append`, which handles the read-then-upsert-with-`ordering=200` convention internally:

```json
{"function":"items.progress_log.append","target":{"kind":"item","item_id":42},"payload":{"headline":"kicked off engineer dispatch","content":"..."}}
```

CLI adapter: `yoke items progress-log append PREFIX-N --headline TEXT --content TEXT` (or `--content-file PATH`); `yoke items section get PREFIX-N --section "Progress Log"` to read. Destructive rewrite: `yoke items section upsert PREFIX-N --section "Progress Log" --content-file PATH --ordering 200`. Reading the existing Progress Log into a shell variable / temp file and piping back into `items section upsert` is structured-field-transform shell choreography that the PreToolUse lint refuses by default.

Why this surface: `shepherd_log`/`shepherd_caveats` are epic architect verdicts; `spec`/`technical_plan`/`worktree_plan` are intent fields, not execution state; `epic_progress_notes` is the equivalent for epic *tasks* keyed `(epic_id, task_num)`; the rendered body is virtual and picks up section writes automatically.

Convention:

- Section name is **exactly** `Progress Log` (case-sensitive, two words).
- `--ordering 200` keeps the section after the standard structured fields (spec=10, design_spec=20, technical_plan=30, etc.) and before any operator-authored sections that have no explicit ordering (default is large).
- Each entry leads with an ISO-8601 UTC timestamp + a short headline so the file becomes a chronological log when read top-to-bottom. The `items.progress_log.append` handler stamps the timestamp automatically.
- The function-call surface (`items.progress_log.append`) preserves prior content and writes one new entry per call; concurrent writers are serialized by the existing item claim.
- Skill prose and agent bodies that drive multi-turn execution against an item should reference this convention rather than inventing per-skill scratchpad surfaces.

## Board

- `.yoke/BOARD.md` is auto-generated and untracked.
- Board rendering logic is Python-owned.
- **The board refreshes only on explicit request.** Nothing in Yoke rebuilds it automatically — item and lifecycle mutations, session start/end, hooks, merge, deploy, and close-out all leave `.yoke/BOARD.md` untouched — so run `yoke board rebuild` when you want a current view. Rebuilds flow through the `board.rebuild.run` function id. Operator/debug adapter: `yoke board rebuild`. Use `yoke board rebuild --print` to print after writing, or `yoke board rebuild --print-only` to render the same board text without updating `.yoke/BOARD.md`. The rebuild composes a `board.data.get` fetch (DB reads server-side; works over BOTH transports, https included) with a client-local render + write — board art and VISION entries stay client-local; board appearance/scope come from DB `project-policy.settings.board`; the machine commit cache is ingest scratch that upserts daily commit/line rollups into `project_code_days` so board and Overview share one code meter.
