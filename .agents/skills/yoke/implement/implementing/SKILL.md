---
name: implementing
description: "Implementation kickoff inside /yoke implement: QA seeding, project context, test commands, and implementation guidance. Called after the item enters its implementation stage."
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: ""
---

# Implementing Sub-skill

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

Called by `implement/entry.md` (or `implement/reentry.md`) after the item is at its implementation stage and the current harness session has provisioned the worktree (same session, no relaunch). The session's authority over the worktree is its work-claim on the item, validated per tool call by `lint_session_cwd`. The sub-skill handles QA seeding and directs the agent to begin implementation.

**Context variables** (passed by the parent skill):
- `{PREFIX-N}` — complete public item ref
- `{NNN}` — zero-padded filename (e.g., `939`)
- `{title}` — item title
- `{WORKTREE_PATH}` — absolute worktree path
- `{_current_executor}` — must be `implement`
- `{_worktree_policy}` — `single_implementation_lane`, or `none` for a laneless workflow

**Exact-path worktree anchor:** All subsequent file operations — Read, Edit, Write, Grep, Glob — MUST use absolute paths rooted at `{WORKTREE_PATH}`, not the main repo. The worktree is an isolated copy; reading a file at the main repo path and then editing it at the worktree path will fail because the Read tool's cached content won't match the worktree copy. Always resolve paths from `{WORKTREE_PATH}` for both investigation and modification.

**Test invocations follow the same anchor.** `pytest`, `python3 -m pytest`, and `yoke watch pytest` MUST collect and run from `{WORKTREE_PATH}`, not the main checkout. The simplest discipline is the Step 0 directive in [`implementation.md`](implementation.md): `cd "{WORKTREE_PATH}"` once at the top of the session, then later pytest invocations resolve relative collection paths under the worktree automatically (sticky-cwd harnesses) or via inlined absolute paths and `--rootdir "{WORKTREE_PATH}"` (static-cwd harnesses). The `watch_pytest` wrapper hard-refuses wrong-cwd invocations under a worktree-bearing claim with a one-line remediation message; if you see that refusal, `cd` and re-run.

**Simplify authoring anchor:** Phase 4 applies the shared `AGENTS.md` `## Simplify — three-axis doctrine` at code-author time. Use existing surfaces first, keep the diff to the smallest AC-satisfying shape, justify new infrastructure against what already exists, and apply the future-concept lens when implementation discovers a later primitive hiding inside current scope.

**Widen-before-edit loop:** At the start of each implementation slice, and before every sibling-module create/edit that was not already named in the current slice, run:

```bash
yoke claims path list --item PREFIX-N --state planned --state active --state blocked
```

Mentally diff the declared coverage against the files you are about to touch. If any file is not covered by a non-terminal claim, widen first with a specific rationale, then edit. This is a recurring checklist item, not a once-at-entry declaration. A future PreToolUse advisory on `Write`/`Edit` is the natural follow-up enforcement layer; blocking enforcement remains the end-of-implementation boundary gate.

This sub-skill is entered only after the parent verifies the pinned `implement`
binding and a single-lane or laneless policy. A task-graph item owned by
`conduct` never reaches this router; that skill's Tester owns its QA loop.

## Phase Dispatch

Read and follow each phase file in order. All phases share the context variables above.

| Phase | File | When |
|---|---|---|
| 1. QA Seeding | `implementing/qa-seeding.md` | Always |
| 1b. Browser Seeding | `implementing/browser-seeding.md` | Browser-testable items only (called from qa-seeding.md) |
| 2. Project Context Preflight | `implementing/project-context.md` | Always (self-skips only for projectless/no-context items) |
| 3. Test Commands & QA Recording | `implementing/test-and-record.md` | Always |
| 4. Implementation Guidance | `implementing/implementation.md` | Always |

**Execution order matters:** The project-context preflight must complete before the text-sensitive audit in `test-and-record.md` and before the file-discovery guidance in `implementation.md`.

**Parallel phase-read optimization:** The agent MAY read phases 1, 2, 3, and 4 in a single parallel tool call before executing any of them. Read Phase 1b only when the item's attached plans or explicit verification contract call for a Browser method case. Pre-loading applicable docs in one round-trip eliminates multiple sequential Read calls.

**IMPORTANT — large files:** When working with large files during implementation, use the Read tool's `offset` and `limit` parameters to load only the needed range. This preserves context window budget. For example, if you need a theme block near the end of a 500-line CSS file, read only that range — do not read the entire file. This guidance appears here (in the router) so it is always visible, even if later phase files are read with offset/limit themselves.
