# /yoke conduct — supplemental files and responsibility map

Read this when a phase step names a supplemental file, or when you need to
know which file owns a conduct responsibility. The phase map on the
entrypoint is the execution route; this is the navigation index behind it.

**Supplemental files — read only when a phase step references them:**

| File | Read when | Safe-read guidance |
|---|---|---|
| `dispatch-context.md` (227 lines) | Steps in the loop reference specific sections (5f-rehydrate, 5m, 5n, 5i-minimal, etc.) | **Read only the referenced section.** Use `offset`/`limit` on the Read tool: section index is at the top of the file. Never read end-to-end. |
| `simulation-autofix.md` (55 lines) | `simulation-gate.md` Branch 3 (GAPS FOUND with CRITICALs) | Read fully only when entering the autofix flow. |
| `error-handling.md` (70 lines) | Reference only — halt conditions and non-halting failure notes | Small enough to read in full when needed. |

**Large-file read discipline for subagent dispatch prompts:** When a phase file builds an Engineer, Tester, or Simulator prompt that references known-large documents (task bodies, diffs, specs), that phase file includes explicit size-gate guidance. Follow it — do not blind-read oversized content into prompts.

## Successor owner map

For adjacent work items that target specific conduct responsibilities:

| Responsibility | Owner file | Notes |
|---|---|---|
| Submission remediation | `engineer-tester-loop.md` (step 5, submission gate) | Current owner for submission-gate routing |
| Reflection capture | `dispatch-context.md` (step 5m) | Unchanged — still in dispatch-context |
| Sync / cleanup | `entry-activation.md` (S6b auto-sync) + `cleanup-report.md` (6z-cleanup) | Split: sync at entry, cleanup at exit |
| Simulation gate | `simulation-gate.md` (S6h) | Current owner for integration simulation |
| Task fan-out enumeration | `entry-activation-resolution.md` (S6c) | Produces `_task_ids`; per-candidate same-worktree and dependency filters applied here |
| Parallel Engineer/Tester dispatch | `dispatch-context-dispatch.md` (5g/5h) + `dispatch-context-prompts.md` (5i) | Live execution path for `_batch_size > 1`; routed from `engineer-tester-loop.md` Branch B |
